# Current Code Map

Updated: 2026-07-19 CST

Generated from current tree at `C:\code\githubstar\wechathtmldownload`.

## 2026-07-19 HUAIDJ weekly visibility candidate map

The active integration copy is
`F:\DevData\HuaidjRuntime\build\weekly-visibility-20260719`. It is a dirty
candidate based on `0b97884db33c`, not the live Hermes release. The discovery
tree at `F:\code\githubstar\wechathtmldownload` and other worktrees remain
protected evidence/donors; see `WORKTREE_CONSOLIDATION_PLAN_20260719.md`.

| Layer | Current candidate authority | Responsibility |
| --- | --- | --- |
| Mini-program date semantics | `apps/weekly_activity_miniprogram/utils/businessDate.js`, `utils/dateVisibility.js`, `utils/datePreview.js`, `services/homeFilters.js` | Asia/Shanghai business day, exact date, tonight, and Friday-Sunday range state |
| Mini-program data identity | `apps/weekly_activity_miniprogram/utils/api.js`, `services/generationContract.js`, `services/facetContract.js` | complete pagination, cache transaction, generation/scope checks, same-visible-set facets |
| Home/render consumers | `apps/weekly_activity_miniprogram/pages/index/index.js` and entity/detail/Atlas pages | preserve filter mode, load current rows, and expose consistent totals/posters/facets |
| CloudBase hot path | `apps/weekly_activity_miniprogram/cloudfunctions/weeklyDataSync/index.js`, `cloudfunctions/weeklyDataSync/dateVisibility.js`, `scripts/run_cloudbase_hot_sync_admin.cjs` | write/validate a new generation, then switch the active config pointer |
| CloudRun weekly API | `services/weekly_activity_cloudrun/src/dataStore.mjs`, `src/dateVisibility.cjs`, `src/server.mjs` | current/package projection, exact/range/city filters, pagination and public identity |
| Model/runtime adapters | `services/weekly_activity_cloudrun/src/qwenVlClient.mjs`, `src/deepSeekClient.mjs` | bounded safe errors/model routing; no client-side credentials |
| Sound lane | `services/weekly_activity_cloudrun/src/soundIngress.mjs`, `src/soundEvidence.mjs`, `src/soundStore.mjs`, `apps/weekly_activity_miniprogram/cloudfunctions/soundSubmissionGateway/` | ingress validation, private evidence boundary, redacted public responses |
| Package generation | `tools/stage7_rewrite/scripts/weekly_public_projection.py`, `weekly_city_routes.py`, `stamp_weekly_api_generation.py` | one public projection, contained route generation, generation stamp and leak gate |
| Daily orchestration | `tools/stage7_rewrite/run_huaidj_sanji_daily_twice.ps1`, `run_openclaw_weekly_daily_publish.ps1` | 744-hour Sanji window, OS-backed single-run lease, Qwen-VL/DeepSeek candidate, optional explicit deploy |
| Release/deploy | `services/weekly_activity_cloudrun/scripts/bake_and_deploy.py`, `direct_cloudbase_deploy.py`, mini-program staging/upload scripts | transactional prepare/deploy/readback and fail-closed upload confirmation |
| Hermes control plane | `tools/stage7_rewrite/scripts/install_huaidj_sanji_hermes_jobs.py`, `audit_huaidj_sanji_hermes_contract.py` | render seven canonical launchers/nine jobs, bind immutable repo/Python/report root, audit drift |
| Atlas dataset identity | `tools/atlas_rebuild/build_atlas_serving_triplet.py`, `atlas_dataset_identity.py`, mini-program Atlas bundles, CloudRun Atlas API | derive immutable `datasetId`, reject mismatched graph/index/neighborhood generations |
| Real-tool acceptance | `apps/weekly_activity_miniprogram/scripts/run_devtools_release_suite_windows.ps1` and `tests/devtools-*.cjs` | bind a verified static package snapshot and run rendered release scenarios |

The main cross-layer invariant is:

```text
complete generation-verified current pages
  -> one date/city visible set
  -> list + total + poster pool + city/date facets
  -> CloudRun/CloudBase/client readback with the same identity
```

Static bundled activity data remains disaster fallback only. Atlas triplet
output is repository-external candidate data; building it does not deploy or
change a serving pointer. None of the 2026-07-19 candidate modules above proves
CloudRun/CloudBase deployment, mini-program upload/public release, Hermes
cutover, the 744-hour run, or Atlas promotion.

## 2026-05-31 User Command Recall / Current Execution Ledger

- `reports\WEEKLY_USER_COMMAND_RECALL_EXECUTION_LEDGER_20260531.md` is the current consolidated ledger for the user's scattered Atlas/HUAIDJ commands.
- The ledger groups takeover, CloudRun, mini-program, DB1/DB2/DB3, DJ/venue relations, DJ Interview, mixtape/outlinks, coordinate repair, OpenClaw, self-wake, runtime memory, and anti-commercial product constitution.
- Current unresolved blocker from that ledger: `Rust Club 锈蚀俱乐部` / `大庆` / `rust_club:74c857fda5f80128` remains without accepted coordinates.
- `docs\longrun\atlas-route-external-db-20260531\loops\loop-016-handoff.md` and `loop-016-scorecard.md` are the latest loop handoff and scorecard.

## 2026-05-31 Tencent Geocode Signature Audit

- `reports\WEEKLY_TENCENT_GEOCODE_SIGNATURE_AUDIT_20260531.md` records the official-doc/source check.
- Official docs checked: Tencent WebService key/signature FAQ and Tencent place search API.
- `tools\stage7_rewrite\scripts\geocode_weekly_activity_places.py` aligns with the docs: sorted params, raw unencoded signature input, matching request path, final URL encoding, and `x-legacy-url-decode:no`.
- Focused verification: `python -m pytest tools\stage7_rewrite\tests\test_geocode_weekly_activity_places.py -q` -> `19 passed`.
- Boundary: no code change and no coordinate write; status `111` is now a key/SK/control-plane blocker unless new official evidence contradicts this.

## 2026-05-31 DevTools Automator WS Diagnosis

- `reports\WEEKLY_MINIPROGRAM_DEVTOOLS_AUTOMATOR_WS_DIAGNOSIS_20260531.md` records the redacted DevTools automator blocker.
- `cli.bat auto --debug` emits a dynamic `ws connect` port; reports record only redacted ticket/token presence, not values.
- Latest proof: `dynamic_ws_port=18964`, `root_socket_opened=true`, `tool_getinfo_response=false`.
- `miniprogram-automator` installed and npm-latest versions are both `0.12.1`, so there is no npm package update to apply.
- Boundary: current rendered behavior gap is automator protocol/bridge setup, not a known frontend assertion failure.

## 2026-05-31 Rust Club Geo Source Recheck

- `reports\WEEKLY_RUST_CLUB_GEO_SOURCE_RECHECK_20260531.md` records the current evidence.
- Current source map path: `services\weekly_activity_cloudrun\data\current_release\source_actions\source_url_map.json`.
- Source hash `74c857fda5f80128` maps to official account `Rust Club 锈蚀俱乐部`, published `2026-05-28`, event `rust_club:74c857fda5f80128`.
- Current detail file has empty address fields and null `geo_lng` / `geo_lat` / `venue_lng` / `venue_lat`, with `geo_source=cleared_invalid_normalized_coordinate`.
- Historical local article `五月一 Rust Club 测试开放 初夏露台` has lake/terrace context but no extracted address lines.
- Boundary: `rust_club_daqing` remains `pending_geocode`; no historical/stale coordinate may be written.

## 2026-05-31 Mini-Program Frontend CLI Test Audit

- `reports\WEEKLY_MINIPROGRAM_FRONTEND_CLI_TEST_AUDIT_20260531.md` records the latest frontend CLI test slice.
- Pure Node/static mini-program tests: `node --test tests/*.test.cjs` from `apps\weekly_activity_miniprogram` -> `68 passed`.
- Clean-CI quality: `ok=true`, package size `876049`, staging files `68`.
- DevTools CLI and `miniprogram-automator` are installed, but rendered behavior scripts are blocked at the automation WebSocket/protocol layer before product assertions.
- Boundary: no upload/review/deploy/data package rebuild/DB write/coordinate write.

## 2026-05-31 Anti-Commercial Product Constitution

- `reports\WEEKLY_ATLAS_ANTI_COMMERCIAL_PRODUCT_BOUNDARY_20260531.md` is the current product-boundary report.
- `tools\stage7_rewrite\DJ_INTERVIEW_MVP_SSOT_20260531.md` now records the anti-commercial product constitution in the DJ Interview SSOT.
- Product boundary: Atlas / HUAIDJ is anti-commercial, underground-first, preservation-first, and cool through archive/relationships, not rankings or sales mechanics.
- Forbidden surfaces: ratings, star scores, paid placement, ad inventory, commercial ranking, review-platform copy, and popularity-score mechanics.

## 2026-05-31 Tencent Geocode Credential Fallback

- `tools\stage7_rewrite\scripts\geocode_weekly_activity_places.py` now builds Tencent credential attempts from paired env names first, then unsigned key fallback.
- Supported pairs: `TENCENT_MAP_KEY/TENCENT_MAP_SK`, `TENCENT_LBS_KEY/TENCENT_LBS_SK`, `QQ_MAP_KEY/QQ_MAP_SK`, `QQ_LBS_KEY/QQ_LBS_SK`, `TX_MAP_KEY/TX_MAP_SK`, and `LBS_KEY/LBS_SK`.
- Provider output records only env names, credential mode, and status; it must not print key/SK values.
- `tools\stage7_rewrite\tests\test_geocode_weekly_activity_places.py` covers paired credential priority and unsigned fallback retention.
- Latest retry: `tools\stage7_rewrite\reports\weekly_geocode_missing_geo_tencent_recall_commands_retry2_20260531`; both paired `TENCENT_MAP_KEY/TENCENT_MAP_SK` and unsigned fallback returned status `111`, accepted `0`.
- Signature audit: `reports\WEEKLY_TENCENT_GEOCODE_SIGNATURE_AUDIT_20260531.md`; local signing code matches official docs, so `111` should not be chased by blind code edits.

## 2026-05-31 CodeGraph Refresh

- `reports\WEEKLY_CODEGRAPH_REFRESH_20260531.md` records the CodeGraph refresh slice.
- `codegraph sync "C:\code\githubstar\wechathtmldownload"` synced `201` changed files: added `145`, modified `56`, indexed `6035` nodes in `12.6s`.
- A second bounded sync synced `1` added file with `0` nodes in `505ms`.
- Full force reindex then brought newly added mini-program pages into the graph, including `pages\interview\interview.js`, `pages\map\map.js`, and `pages\sound\sound.js`.
- `.gitignore` now excludes local scratch artifacts `tmp-dajiala-app.js` and `tmp-site-inspect/`, so CodeGraph does not treat them as source residuals.
- Current status after post-S13 sync: initialized `true`, files `2990`, nodes `70041`, edges `187441`, pending added `0`, pending modified `0`, pending removed `0`.
- Boundary: CodeGraph index refresh only; no deploy/upload/DB/graph/vector mutation.

## 2026-05-31 External Music Link Field Bridge

- `services\weekly_activity_cloudrun\src\externalMusicLinks.mjs` normalizes DJ Interview Instagram / mixtape / source URLs into canonical private link metadata.
- `services\weekly_activity_cloudrun\src\interviewStore.mjs` stores `externalLinksSchemaVersion`, `externalLinks`, `musicLinks`, and `externalLinkSafety` on the private sidecar entry.
- `services\weekly_activity_cloudrun\tests\externalMusicLinks.test.mjs` covers platform detection, URL hash, rights status, invalid URL rejection, and no-download/no-cache safety flags.
- `services\weekly_activity_cloudrun\tests\djInterviewStore.test.mjs` now asserts list redaction keeps raw URLs private while exposing only link counts/booleans.
- Report: `reports\WEEKLY_EXTERNAL_MUSIC_LINK_FIELD_BRIDGE_20260531.md`.
- Verification: PRD JSON parse `prd json ok`; targeted external/interview tests `5 passed`; `npm run weekly-api:test` `96 passed`; CodeGraph post-S13 pending `0/0/0`.
- Boundary: no DB1/DB2/DB3 write, no current release rebuild, no public graph/vector promotion, no audio handling, no deploy/upload.

## 2026-05-31 Backend / Frontend Deploy

- `reports\WEEKLY_DJ_INTERVIEW_BACKEND_FRONTEND_DEPLOY_20260531.md` records the latest deployed state.
- Active CloudRun backend is now `weekly-api-017`.
- Mini-program developer version is now `2026.05.31.2`, desc `atlas-dj-interview-openclaw-db-guard`.
- Deploy evidence: `tools\stage7_rewrite\reports\cloudrun_direct_api_deploy_dj_interview_20260531\cloudrun_direct_api_deploy_report.json`.
- Public smoke evidence: `tools\stage7_rewrite\reports\cloudbase_route_db_longrun_smoke_after_dj_interview_20260531\cloudrun_weekly_production_smoke.md`.

## 2026-05-31 DB / Incremental Build Guard

- `reports\WEEKLY_DB_UNIFICATION_AND_INCREMENTAL_BUILD_AUDIT_20260531.md` records DB1/DB2/DB3 authority, field merge rules, and incremental build work queue.
- `services\weekly_activity_cloudrun\scripts\bake_and_deploy.py` now builds a deploy-context fingerprint manifest and reuses unchanged contexts.
- `tools\stage7_rewrite\tests\test_smoke_cloudrun_weekly_production.py` covers unchanged-context reuse.

## 2026-05-31 OpenClaw Active Skill

- `\\wsl.localhost\Ubuntu\home\pc\.openclaw\plugin-skills\openclaw-pipeline\SKILL.md` now has top-priority section `0.1 2026-05-31 当前执行覆盖规则`.
- `reports\WEEKLY_OPENCLAW_ACTIVE_SKILL_UPDATE_20260531.md` records the verification.
- Guarded runtime checks: `tools\stage7_rewrite\scripts\audit_weekly_openclaw_pipeline_geo_boundary.py`, `test_audit_weekly_openclaw_pipeline_geo_boundary.py`, `test_geocode_weekly_activity_places.py`, and `test_run_ocr_direct_safe_cli.py`.

## 2026-05-31 DJ Interview TabBar Navigation

- `apps\weekly_activity_miniprogram\pages\artist\artist.js` now seeds `atlasDjInterviewSeed:v1` and opens the interview tab with `wx.switchTab()` rather than `wx.navigateTo()` with query params.
- `apps\weekly_activity_miniprogram\pages\interview\interview.js` reads and removes that seed on load, while direct `djName` / `city` query values still win when present.
- `apps\weekly_activity_miniprogram\pages\about\about.js` uses `wx.reLaunch()` fallback for the tabBar page and keeps `ABOUT_TAB_INDEX = 3`.
- `apps\weekly_activity_miniprogram\app.js` also keeps `ABOUT_TAB_INDEX = 3` for sound-notice red dots.
- `apps\weekly_activity_miniprogram\tests\interview-column.test.cjs` locks the tabBar navigation contract.

## 2026-05-31 Deploy / Upload Boundary

- `reports\WEEKLY_DEPLOY_UPLOAD_BOUNDARY_AUDIT_20260531.md` is the current deploy/upload read-only audit.
- Backend final-stage deploy authority: `services\weekly_activity_cloudrun\scripts\bake_and_deploy.py` and `services\weekly_activity_cloudrun\scripts\direct_cloudbase_deploy.py`.
- Backend safe preflight forms: `bake_and_deploy.py --prepare-only` and `bake_and_deploy.py --dry-run`.
- Mini-program final-stage upload authority: `apps\weekly_activity_miniprogram\scripts\upload_native_windows.ps1`; safe preview is `-WhatIf`.
- Mini-program quality gate: `apps\weekly_activity_miniprogram\scripts\Test-CleanCiQuality.ps1`.

## 2026-05-31 Weekly Wake Fingerprint

- `tools\stage7_rewrite\scripts\compute_weekly_wake_fingerprint.py` computes the 5-minute wake preflight fingerprint from tracked files, optional failed-gate JSON summaries, and optional pending JSONL queues.
- `tools\stage7_rewrite\tests\test_compute_weekly_wake_fingerprint.py` covers unchanged no-op, changed file, failed gate, and pending queue behavior.
- `reports\WEEKLY_WAKE_FINGERPRINT_20260531.md` records the current decision and real two-run proof.
- Output contract:
  - `skipped_no_actionable_problem`
  - `run_fingerprint_changed`
  - `run_actionable_problem`
- Safety flags stay false for rebuild, geocode, OCR, deploy, upload, and LLM calls.

## 2026-05-31 External/Mixtape Gate And DJ Interview Main Column

- `tools\stage7_rewrite\scripts\run_atlas_social_outlink_bounded_fetch.py` blocks media/attachment responses before body reads and reports blocked metadata only.
- `tools\stage7_rewrite\scripts\run_atlas_source_acquisition_bounded_fetch.py` blocks media/attachment responses before body reads and no longer persists non-HTML artifacts.
- `tools\stage7_rewrite\scripts\validate_public_social_links.py` applies the same pre-body media/attachment gate for public social-link validation.
- Tests: `tools\stage7_rewrite\tests\test_run_atlas_social_outlink_bounded_fetch.py`, `test_run_atlas_source_acquisition_bounded_fetch.py`, and `test_validate_public_social_links.py`.
- `apps\weekly_activity_miniprogram\utils\sourceAction.js` now returns an empty URL on source-map/API misses instead of inventing a WeChat `/s/<hash>` URL.
- `apps\weekly_activity_miniprogram\pages\interview\interview.js|wxml|wxss` is the primary DJ Interview form for DJ name, city, private contact, Instagram URL, mixtape/source URL, short answer, and consent flags.
- `apps\weekly_activity_miniprogram\app.json` adds the interview page to the mini-program tabBar; `app.js` moves the About red-dot index accordingly.
- `apps\weekly_activity_miniprogram\pages\about\about.js|wxml|wxss` adds a main interview panel; `pages\artist\artist.js|wxml|wxss` adds a DJ-profile interview CTA.
- `services\weekly_activity_cloudrun\src\interviewStore.mjs` is a private sidecar store; list responses redact raw contact and answer text.
- `services\weekly_activity_cloudrun\src\server.mjs` adds `/api/v1/atlas/dj-interviews` for GET/POST.
- Tests: `apps\weekly_activity_miniprogram\tests\interview-column.test.cjs`, `services\weekly_activity_cloudrun\tests\djInterviewStore.test.mjs`, and `services\weekly_activity_cloudrun\tests\djInterviewApi.test.mjs`.
- SSOT: `tools\stage7_rewrite\DJ_INTERVIEW_MVP_SSOT_20260531.md`.
- Boundary: this code path stores original links and consent only; no audio download/cache/proxy, no Atlas serving DB write, and no graph promotion.

## 2026-05-31 Weekly Missing-Geo Provider Recheck

- `tools\stage7_rewrite\scripts\geocode_weekly_activity_places.py` supports `--only-missing-geo`, so Tencent/Amap rechecks can target only rows whose current release item lacks usable `geo_lng` / `geo_lat`.
- The same script now tries Tencent paired key/SK credentials before unsigned fallback, avoiding a stale first SK/key selection from exhausting the run.
- `tools\stage7_rewrite\tests\test_geocode_weekly_activity_places.py` covers valid/invalid geo alias handling, OpenClaw env names, Tencent signed query generation, paired credential priority, and unsigned fallback retention.
- Current queue output: `tools\stage7_rewrite\reports\weekly_geocode_missing_geo_queue_20260531\report.json`, `item_count=1`, candidate `rust_club:74c857fda5f80128`.
- Current provider outputs: Tencent Windows and WSL both rejected with status `111`; Amap WSL returned OK but `strong_place_matches=0`.
- Latest Tencent retry after credential fallback: `tools\stage7_rewrite\reports\weekly_geocode_missing_geo_tencent_recall_commands_retry2_20260531`, `tencent_credential_attempt_count=2`, accepted `0`, review `2`, both status `111`.
- Current decision report: `reports\WEEKLY_GEOCODE_MISSING_GEO_PROVIDER_RECHECK_20260531.md`; `rust_club_daqing` remains `pending_geocode`.
- Current source recheck report: `reports\WEEKLY_RUST_CLUB_GEO_SOURCE_RECHECK_20260531.md`; current source/detail/historical local text still does not justify a coordinate write.
- Boundary: this is a provider/source evidence gate only. The geocode script must not write coordinates unless accepted by provider/source cross-check.

## 2026-05-31 Atlas DB Contract + Weekly LLM Materialization

- `tools\stage7_rewrite\scripts\audit_atlas_db_field_contract.py` is the report-only contract mapper for Atlas DB1/DB2/DB3, weekly current coverage, miniapp GZ counts, and canonical field groups.
- `tools\stage7_rewrite\tests\test_audit_atlas_db_field_contract.py` covers the contract report against fixture DBs/current packages.
- Current output: `tools\stage7_rewrite\reports\atlas_db_field_contract_20260531\atlas_db_field_contract.json`; decision `atlas_db_field_contract_ready`.
- Current DB authority: DB1 source/raw Atlas under `reports\atlas_incremental_wechat_refresh_20260522_1438\...atlas.sqlite`; DB2 serving read model under `reports\atlas_serving_time_overlay_span_split_search_date_refresh_candidate_20260527_2018\atlas_serving.sqlite`; DB3 miniapp sqlite/GZ under `services\weekly_activity_cloudrun\data\atlas_miniapp.sqlite` and `services\weekly_activity_cloudrun\data\atlas_index.json.gz`.
- `services\weekly_activity_cloudrun\data\atlas_serving.sqlite` is inaccessible/untrusted and must not be used as authority.
- `services\weekly_activity_cloudrun\scripts\materialize_source_grounded_outputs.mjs` can rebuild Weekly materialized LLM summary/index/detail from release fields without DeepSeek or paid API calls; it now repaired the current package to `208/208` index coverage.
- `services\weekly_activity_cloudrun\scripts\bake_and_deploy.py` stages the repaired `data/current_release/llm` directory into `tmp\cloudrun_deploy_context`.
- `services\weekly_activity_cloudrun\scripts\direct_cloudbase_deploy.py` deployed that context through direct CloudBase API as `weekly-api-016` in that slice; current active backend is now `weekly-api-017`, see `reports\WEEKLY_DJ_INTERVIEW_BACKEND_FRONTEND_DEPLOY_20260531.md`.
- `tools\stage7_rewrite\scripts\smoke_cloudrun_weekly_production.py` is the production smoke gate. Current output `tools\stage7_rewrite\reports\cloudbase_route_db_longrun_smoke_after_llm_index_20260531\cloudrun_weekly_production_smoke.json` is ready with blockers `[]`.

## 2026-05-31 Weekly Atlas Relation Surface Guard

- `tools\stage7_rewrite\scripts\audit_weekly_atlas_relation_surface.py` is the report-only guard for mini-program Atlas relation fields in the packaged `services\weekly_activity_cloudrun\data\atlas_index.json.gz`.
- The guard checks artist history, artist frequent venues, artist collaborators / same-event counts, source-ref lookup coverage, venue history, and venue resident DJs.
- Current report output: `tools\stage7_rewrite\reports\weekly_atlas_relation_surface_audit_20260531\weekly_atlas_relation_surface_audit.json`; decision `weekly_atlas_relation_surface_passed`, findings `0`.
- Local audited samples: `Ozone` events/collaborators/venues/source refs `100/30/20/100`; `OIL` events/resident DJs/source refs `2494/1105/2494`; `POOLS` events/resident DJs/source refs `4/3/4`.
- Public probe coverage is built into the script with `--default-public-base` and currently passes against `https://weekly-api-255880-4-1371956557.sh.run.tcloudbase.com` for `Ozone`, `OIL`, and `POOLS`.
- `services\weekly_activity_cloudrun\tests\miniappAtlasApi.test.mjs` now asserts artist frequent venues, collaborators, and `sameEventCount` in the backend read model fixture.
- `apps\weekly_activity_miniprogram\tests\ra-entity-navigation.test.cjs` now asserts the frontend preserves artist collaborators/frequent venues and venue resident DJs even when the weekly list is empty.
- Boundary: guard/test/report only in this slice; runtime relation behavior already passes on CloudRun `weekly-api-015`, so no new backend deploy or mini-program upload was performed for this audit closeout.

## 2026-05-31 Weekly Venue DB Geo Coverage

- `tools\stage7_rewrite\registries\weekly_venues_seed.json` is now self-contained for active venue coordinates: `73/73` active venues have `geo_lng` / `geo_lat`.
- `nuts_chongqing` and `gas_nation_tianjin` were backfilled from current-release coordinate evidence for the same verified addresses, removing the last active registry geo gaps.
- `rust_club_daqing` is explicit `pending_geocode`, not active: source evidence points to 大庆, the stale Beijing coordinate was cleared, and precise street-level address/coordinate remains unresolved.
- `tools\stage7_rewrite\scripts\archive_old\validate_weekly_registries.py` allows `pending_geocode` for venue rows and still warns/fails active venue gaps.
- `tools\stage7_rewrite\scripts\audit_weekly_venue_registry_geo_coverage.py` compares the fixed registry against `services\weekly_activity_cloudrun\data\current_release\current.json` without map API calls or writes.
- Regression coverage: `tools\stage7_rewrite\tests\test_audit_weekly_venue_registry_geo_coverage.py` and `tools\stage7_rewrite\tests\test_weekly_registries.py`.
- Current audit output: `tools\stage7_rewrite\reports\weekly_venue_registry_geo_coverage_20260531\weekly_venue_registry_geo_coverage.json`; decision `weekly_venue_registry_geo_coverage_passed_with_known_blockers`, current release geo coverage `207/208`, unexpected missing geo rows `0`, registry backfill candidates `0`, registry/current mismatches above `2500m` `0`.
- Boundary: fixed registry/test/report only; no release rebuild, deploy/upload, Tencent/Amap API call, or quota use.

## 2026-05-31 Weekly OpenClaw Pipeline Venue DB Geo Boundary

- Live WSL scripts `\\wsl.localhost\Ubuntu\home\pc\scripts\huaidj-weekly-openclaw-stable.sh` and `\\wsl.localhost\Ubuntu\home\pc\scripts\huaidj-weekly-pipeline.sh` no longer perform venue anchor patching, geocoding, or `zero_geo_count` blocking.
- `huaidj-weekly-openclaw-stable.sh` keeps release required-field/source-map validation but treats coordinates as fixed venue DB data, not as a pipeline geocode output gate.
- `huaidj-weekly-pipeline.sh` keeps the Step 2.5 placeholder as a comment only; no `anchor_patch()` function/call remains.
- `huaidj-weekly-openclaw-stable.sh` now defines `SCRIPT_DIR` from `BASH_SOURCE[0]` so self-loop quality hooks resolve from the script directory in cron/OpenClaw runs.
- `tools\stage7_rewrite\scripts\audit_weekly_openclaw_pipeline_geo_boundary.py` provides the report-only regression audit for these live scripts. It ignores comment-only mentions but blocks operational `apply_venue_anchors.py`, `anchor_patch(`, `zero_geo_count`, geocode runner calls, and map-API geo key wiring.
- Regression coverage: `tools\stage7_rewrite\tests\test_audit_weekly_openclaw_pipeline_geo_boundary.py`.
- Current live audit output: `tools\stage7_rewrite\reports\weekly_openclaw_pipeline_geo_boundary_audit_20260531\weekly_openclaw_pipeline_geo_boundary_audit.json`.
- Boundary: WSL script reliability and pipeline policy only; no deploy/upload/release rebuild/geocode call.

## 2026-05-31 Weekly Coordinate Repair Guard

- `tools\stage7_rewrite\scripts\repair_weekly_current_resource_fields.py` now builds venue lookup keys with city-scoped variants before plain IDs/names, avoiding same-name multi-city collisions such as stale plain venue IDs winning over the current city.
- The same script now treats frontend map book, registry, and 20260522 historical coordinates as backfill-only when the current item already has trusted Amap/Tencent/cross-check coordinates.
- DeepSeek/known-correction coordinates can still fix large moves, but cannot nudge a trusted provider coordinate for small deltas below `120m`.
- Event-specific venue correction reporting is idempotent once the fields are already corrected.
- `tools\stage7_rewrite\scripts\geocode_weekly_activity_places.py` now recognizes OpenClaw `LBS_KEY` / `LBS_SK` env names and disables Tencent geocoding for the rest of the run after fatal auth/config statuses `110/111/112/120`, avoiding full-queue loops when the SK/IP/referrer/key config is wrong.
- Regression coverage: `tools\stage7_rewrite\tests\test_repair_weekly_current_resource_fields.py` and geocode/apply tests; final dry-run proof `tools\stage7_rewrite\reports\weekly_resource_field_repair_dryrun_final_guard_20260531\weekly_resource_field_repair_report.json`.
- Boundary: code/test/doc/report only; no current release or registry mutation.

## 2026-05-31 Weekly Poster OCR Main-Poster Weighting Repair

- `tools\stage7_rewrite\scripts\archive_old\enrich_weekly_activity_pack_with_poster_ocr.py` now scores poster OCR candidates by information density and demotes QR/payment/menu/map/logo/sponsor/ticket-only artwork. Empty OCR text no longer wins by dimensions alone.
- `tools\stage7_rewrite\tests\test_weekly_activity_poster_ocr_enrichment.py` covers score demotion and end-to-end selection of `main.jpg` over `ticket.jpg`.
- `apps\weekly_activity_miniprogram\utils\posterPool.js` already had matching frontend behavior; `apps\weekly_activity_miniprogram\tests\poster-pool.test.cjs` keeps that contract covered.
- DeepSeek no-thinking enrichment routing was not changed; focused DeepSeek tests were rerun to verify no contract drift.
- Boundary: local pipeline/test/doc change only; no CloudRun redeploy and no new mini-program upload.

## 2026-05-31 Weekly Atlas Source Contract Repair

- `apps\weekly_activity_miniprogram\utils\sourceAction.js`, `utils\sourceArticles.js`, and `pages\source\source.js` now treat `activity_src:*` and `source_ref:*` as Atlas evidence refs instead of opaque article hashes.
- `apps\weekly_activity_miniprogram\pages\venue\venue.js` and `pages\venue\venue.wxml` route Atlas historical event taps to source evidence; `pages\artist\artist.js` and `pages\artist\artist.wxml` do the same for artist history rows.
- `services\weekly_activity_cloudrun\src\miniappAtlasApi.mjs` computes venue resident DJs from the full historical event set before slicing display events by `eventLimit`.
- `tools\stage7_rewrite\scripts\audit_weekly_full_chain_contract.py` emits the current release / Atlas index / mini-program source-consumer contract audit at `tools\stage7_rewrite\reports\weekly_full_chain_contract_audit_20260531`.
- Regression coverage: `apps\weekly_activity_miniprogram\tests\ra-entity-navigation.test.cjs`, `apps\weekly_activity_miniprogram\tests\page-source-routing.test.cjs`, `apps\weekly_activity_miniprogram\tests\format-quality.test.cjs`, and `services\weekly_activity_cloudrun\tests\miniappAtlasApi.test.mjs`.
- Deployment evidence: `tools\stage7_rewrite\reports\cloudrun_atlas_source_contract_repair_20260531\cloudrun_direct_api_deploy_report.json`, mini-program upload log `artifacts\miniprogram-ci-logs\devtools-upload-20260531-1-atlas-source-history-contract.log`, and report `reports\WEEKLY_ATLAS_SOURCE_CONTRACT_REPAIR_20260531.md`.
- Boundary: CloudRun backend deployed and mini-program developer version uploaded; no WeChat review/public release, no huaidj.club upload, no Atlas source/raw DB mutation, no graph/vector write.

## 2026-05-27 Atlas Final Candidate Preflight And Year-Context Review

- `tools\stage7_rewrite\scripts\build_atlas_t6_time_title_year_context_review_packet.py` consumes `tools\stage7_rewrite\reports\atlas_t6_time_title_year_span_recovery_20260527\year_span_context_review_required_rows.jsonl`, classifies source-artifact, weekday-year, conflict/ambiguous, and guide/news blockers, and refuses title-only year/month-day ambiguity.
- Regression coverage: `tools\stage7_rewrite\tests\test_build_atlas_t6_time_title_year_context_review_packet.py`.
- Final candidate preflight output: `reports\atlas_serving_time_city_year_span_final_candidate_preflight_20260527_2145\promotion_preflight.json`.
- Top reports: `reports\ATLAS_T5_T6_TIME_CITY_YEAR_SPAN_FINAL_CANDIDATE_PREFLIGHT_20260527.md` and `reports\ATLAS_T6_TIME_TITLE_YEAR_CONTEXT_REVIEW_20260527.md`.
- Handoff artifacts: `NEXT_AGENT_HANDOFF_ATLAS_FULL_PRODUCTION_20260527.md` and `NEXT_AGENT_HANDOFF_ATLAS_FULL_PRODUCTION_20260527.html`.
- Counts: final candidate/baseline table counts match; graph-window gap `0`; forbidden/noise hits `0`; T6 year-context review ready/blocked `0/1366` with source-artifact `443`, weekday-year `647`, conflict/ambiguous `276`, guide/news `41`; leak hits `0/0/0`.
- Boundary: local/report-only; selected serving, source/raw DB, graph/vector/public pointer, huaidj.club, CloudRun/VPS, mini-program, memory, network/OCR/model, 9router, and D-root unchanged.

## 2026-05-27 Atlas Span/Split Time Recovery And Serving Overlay

- `tools\stage7_rewrite\scripts\build_atlas_t6_time_title_span_split_review_packet.py` consumes `span_split_review_required_rows.jsonl`, applies conservative deterministic split rules, blocks multi-event guide/news rows, and emits report-only ready/blocked rows.
- Regression coverage: `tools\stage7_rewrite\tests\test_build_atlas_t6_time_title_span_split_review_packet.py`.
- The existing readback, source/raw time ISO preflight/execution, serving overlay, search/graph smoke, search-date refresh, local API smoke, and package preflight scripts were reused with explicit input/output paths for the span/split lane.
- Current outputs: `reports\ATLAS_T6_TIME_TITLE_SPAN_SPLIT_REVIEW_20260527.md`, `reports\ATLAS_T6_TIME_TITLE_SPAN_SPLIT_READBACK_GATE_20260527.md`, `reports\ATLAS_T5_TIME_ISO_SPAN_SPLIT_WRITE_EXECUTION_GATE_20260527.md`, `reports\ATLAS_T5_SERVING_TIME_OVERLAY_SPAN_SPLIT_SEARCH_DATE_REFRESH_GATE_20260527.md`, and `reports\ATLAS_T5_SERVING_TIME_OVERLAY_SPAN_SPLIT_LOCAL_API_PACKAGE_PREFLIGHT_20260527.md`.
- Current candidate DB: `reports\atlas_serving_time_overlay_span_split_search_date_refresh_candidate_20260527_2018\atlas_serving.sqlite`.
- Counts: span/split ready/blocked `14/2`; source/raw `events.time_iso` committed rows `51`; serving changed rows `395`; search-date refresh rows `47`; API/browser `25/25` and `5/5`; leak hits `0/0/0`.
- Boundary: source/raw write scope `events.time_iso only`; selected serving DB, graph/vector/public pointer, huaidj.club, CloudRun/VPS, mini-program, memory, network/OCR/model, 9router, and D-root unchanged.

## 2026-05-27 Atlas Time Year/Span Recovery And Serving Overlay

- `tools\stage7_rewrite\scripts\build_atlas_t5_serving_time_overlay_local_api_package_preflight.py` builds the report-only/local-only package/API contract for the cumulative time year/span serving candidate, joining local API smoke, browser smoke, search-date refresh evidence, and a prepared local CloudRun context.
- Regression coverage: `tools\stage7_rewrite\tests\test_build_atlas_t5_serving_time_overlay_local_api_package_preflight.py`.
- Current package/API output: `reports\ATLAS_T5_SERVING_TIME_OVERLAY_YEAR_SPAN_LOCAL_API_PACKAGE_PREFLIGHT_20260527.md`, summary `tools\stage7_rewrite\reports\atlas_t5_serving_time_overlay_year_span_local_api_package_preflight_20260527\serving_time_overlay_local_api_package_preflight_summary.json`, contract `serving_time_overlay_local_api_package_contract.json`, and package context `reports\atlas_serving_time_year_span_overlay_cloudrun_context_20260527_1815\atlas_serving_sqlite_cloudrun_context.json`.
- Package counts: API/browser `24/24` and `5/5`; search-date matches `380/380`; candidate alignment `1`; package context ready `1`; sidecars copied `2`; leak hits `0/0/0`.
- Package boundary: local package/API evidence only; no deploy, public upload, source/raw DB open, selected serving mutation, graph/vector/public/memory action.
- `tools\stage7_rewrite\scripts\build_atlas_t6_time_title_year_span_recovery_packet.py` consumes the T6 `month_day_year_required_rows.jsonl` and `span_or_range_review_required_rows.jsonl` queues, releases deterministic single-year/single-month-day and range-start candidates, and emits report-only ready/blocker queues.
- Regression coverage: `tools\stage7_rewrite\tests\test_build_atlas_t6_time_title_year_span_recovery_packet.py`.
- `tools\stage7_rewrite\scripts\build_atlas_t5_serving_time_overlay_candidate.py` now accepts `--report`, allowing cumulative report-local candidates to write separate evidence reports without overwriting the earlier 09:29 candidate report.
- Current real outputs: recovery/readback/write reports `reports\ATLAS_T6_TIME_TITLE_YEAR_SPAN_RECOVERY_20260527.md`, `reports\ATLAS_T6_TIME_TITLE_YEAR_SPAN_READBACK_GATE_20260527.md`, `reports\ATLAS_T5_TIME_ISO_YEAR_SPAN_WRITE_EXECUTION_GATE_20260527.md`; serving reports `reports\ATLAS_T5_SERVING_TIME_OVERLAY_YEAR_SPAN_CANDIDATE_20260527.md`, `reports\ATLAS_T5_SERVING_TIME_OVERLAY_YEAR_SPAN_SEARCH_GRAPH_SMOKE_20260527.md`, and `reports\ATLAS_T5_SERVING_TIME_OVERLAY_YEAR_SPAN_SEARCH_DATE_REFRESH_GATE_20260527.md`.
- Current candidate DB: `reports\atlas_serving_time_overlay_year_span_search_date_refresh_candidate_20260527_1804\atlas_serving.sqlite`.
- Counts: recovery ready rows `64`; source/raw `events.time_iso` committed rows `242`; serving changed rows `2,703`; search-date refresh rows `380`; local API/browser smoke `ok=true`; leak hits `0/0/0`.
- Boundary: source/raw write scope `events.time_iso only`; selected serving DB, graph/vector/public pointer, huaidj.club, CloudRun/VPS, mini-program, memory, network/OCR/model, 9router, and D-root unchanged.
- Next resume pointer: `tools\stage7_rewrite\reports\atlas_t5_serving_time_overlay_year_span_search_date_refresh_gate_20260527\serving_time_overlay_search_date_refresh_summary.json`.

## 2026-05-27 Atlas Entity Merge Second-Pass Local API Package Preflight

- `tools\stage7_rewrite\scripts\build_atlas_entity_merge_secondpass_local_api_package_preflight.py` consumes the second-pass entity-merge validation summary, local Stage7 API/browser smoke, and local CloudRun context report, then emits a report-only package/API contract for the accepted DeepSeek Pro sidecar.
- Regression coverage: `tools\stage7_rewrite\tests\test_build_atlas_entity_merge_secondpass_local_api_package_preflight.py`.
- Current real outputs: `reports\ATLAS_ENTITY_MERGE_SECONDPASS_LOCAL_API_PACKAGE_PREFLIGHT_20260527.md`, `tools\stage7_rewrite\reports\atlas_entity_merge_secondpass_local_api_package_preflight_20260527\entity_merge_secondpass_local_api_package_preflight_summary.json`, and `entity_merge_secondpass_local_api_package_contract.json`.
- Counts: API checks `24/24`; browser checks `5/5`; mobile entity checks `6/6`; known cases `3/3`; queue/latest decisions `28,853/28,853`; missing decisions `0`; final merge groups / merged subjects `7,094/24,609`; review/split rows `9,082/7,424`; duplicate subject/member-count/forbidden-hit counts `0/0/0`; package sidecars copied `2/2`; leak hits `0/0/0`.
- Boundary: local package/API contract only; no source/raw DB open/write, selected serving mutation/rebuild, graph/vector/public pointer mutation, huaidj.club upload, CloudRun/VPS deploy, mini-program, memory, credential, network/OCR/model, 9router, or D-root action.
- Next resume pointer: `tools\stage7_rewrite\reports\atlas_entity_merge_secondpass_local_api_package_preflight_20260527\entity_merge_secondpass_local_api_package_preflight_summary.json`.

## 2026-05-27 Atlas T5 Serving Time Overlay Search-Date Refresh Gate

- `tools\stage7_rewrite\scripts\build_atlas_t5_serving_time_overlay_search_date_refresh_gate.py` consumes the time overlay search/graph smoke summary and changed rows, copies the report-local candidate DB, updates only event `search_document.search_text` rows touched by the time overlay, rebuilds `search_document_fts`, and emits rollback/readback evidence.
- Regression coverage: `tools\stage7_rewrite\tests\test_build_atlas_t5_serving_time_overlay_search_date_refresh_gate.py`.
- Current real outputs: `reports\ATLAS_T5_SERVING_TIME_OVERLAY_SEARCH_DATE_REFRESH_GATE_20260527.md`, `tools\stage7_rewrite\reports\atlas_t5_serving_time_overlay_search_date_refresh_gate_20260527\serving_time_overlay_search_date_refresh_summary.json`, refreshed rows, rollback contracts, postwrite readback rows, and candidate DB `reports\atlas_serving_time_overlay_search_date_refresh_candidate_20260527_1518\atlas_serving.sqlite`.
- Counts: event refresh target rows `394`; search document update rows `394`; search text changed rows `394`; postwrite search text/FTS date matches `394/394`; rollback/postwrite contracts `394/394`; table-count drift rows `0`; local API/browser smoke `ok=true`.
- Boundary: report-local candidate DB mutation only; no source/raw DB open/write, selected serving mutation, serving rebuild, graph/vector/public pointer mutation, huaidj.club upload, CloudRun/VPS, mini-program, memory, credential, network/OCR/model, 9router, or D-root action.
- Next resume pointer: `tools\stage7_rewrite\reports\atlas_t5_serving_time_overlay_search_date_refresh_gate_20260527\serving_time_overlay_search_date_refresh_summary.json`.

## 2026-05-27 Atlas T5 Serving Time Overlay Search/Graph Smoke

- `tools\stage7_rewrite\scripts\build_atlas_t5_serving_time_overlay_search_graph_smoke.py` consumes the report-local serving time overlay candidate summary and changed rows, opens the candidate DB read-only, validates `performance_event.starts_at`, `dj_event.starts_at`, event search-document presence/date refresh status, graph-window seeds for affected DJs, metric drift, local smoke rollup, and leak guards.
- Regression coverage: `tools\stage7_rewrite\tests\test_build_atlas_t5_serving_time_overlay_search_graph_smoke.py`.
- Current real outputs: `reports\ATLAS_T5_SERVING_TIME_OVERLAY_SEARCH_GRAPH_SMOKE_20260527.md`, `tools\stage7_rewrite\reports\atlas_t5_serving_time_overlay_search_graph_smoke_20260527\serving_time_overlay_search_graph_smoke_summary.json`, `serving_time_overlay_api_contract.json`, readback/search/graph samples, and failed rows.
- Counts: changed rows input `3333`; performance_event starts_at matches `394`; dj_event starts_at matches `2939`; event search docs present/missing `394/0`; event search text missing date rows `349`; graph window seeds/missing seeds `292/0`; metric drift rows `0`; search-date refresh required rows `394`; local API/browser smoke `ok=true`.
- Boundary: candidate serving DB read-only only; no source/raw DB open/write, selected serving mutation, serving rebuild, graph/vector/public pointer mutation, huaidj.club upload, CloudRun/VPS, mini-program, memory, credential, network/OCR/model, 9router, or D-root action.
- Next resume pointer: `tools\stage7_rewrite\reports\atlas_t5_serving_time_overlay_search_graph_smoke_20260527\serving_time_overlay_search_graph_smoke_summary.json`.

## 2026-05-27 Atlas T5 Time ISO Write + Serving Time Overlay Candidate

- `tools\stage7_rewrite\scripts\build_atlas_t5_time_iso_write_preflight_packet.py` consumes the T6 time-title readback-ready rows, validates explicit source/raw target DB provenance, opens the source/raw Atlas SQLite read-only, maps the safe exact-date subset to `events.time_iso`, and emits prewrite snapshots, rollback contracts, postwrite contracts, duplicate selector groups, conflict groups, and blocked rows.
- `tools\stage7_rewrite\scripts\run_atlas_t5_time_iso_write_execution_gate.py` revalidates the preflight, schema hash, row hashes, empty target column, rollback requirements, and confirm token, then updates only `events.time_iso` inside one transaction with postwrite readback.
- `tools\stage7_rewrite\scripts\build_atlas_t5_serving_time_overlay_candidate.py` copies the report-local city overlay serving DB and applies only verified `starts_at` deltas to a new report-local serving candidate, avoiding the earlier full rebuild path that regressed selected serving coverage.
- Regression coverage: `tools\stage7_rewrite\tests\test_build_atlas_t5_time_iso_write_preflight_packet.py`, `tools\stage7_rewrite\tests\test_run_atlas_t5_time_iso_write_execution_gate.py`, and `tools\stage7_rewrite\tests\test_build_atlas_t5_serving_time_overlay_candidate.py`.
- Current real outputs: `reports\ATLAS_T5_TIME_ISO_WRITE_PREFLIGHT_PACKET_20260527.md`, `reports\ATLAS_T5_TIME_ISO_WRITE_EXECUTION_GATE_20260527.md`, `reports\ATLAS_T5_SERVING_TIME_OVERLAY_CANDIDATE_20260527.md`, `tools\stage7_rewrite\reports\atlas_t5_time_iso_write_execution_gate_20260527\time_iso_write_execution_summary.json`, `tools\stage7_rewrite\reports\atlas_t5_serving_time_overlay_candidate_20260527\serving_time_overlay_summary.json`, and candidate DB `reports\atlas_serving_time_overlay_candidate_20260527_0925\atlas_serving.sqlite`.
- Counts: preflight input/mapped/blocked readback rows `78/75/3`; raw `events.time_iso` targets `690`; duplicate selector groups `132`; conflict groups `0`; source/raw committed rows `690`; postwrite match rows `690`; serving candidate changed rows `3333` split performance_event/dj_event `394/2939`; table-count drift `0`; local API/browser smoke `ok=true`.
- LLM audit: source/raw target column is `events.time_iso`, not serving `starts_at`; a list self-extension hang in date matching was fixed; month/day-only evidence is accepted only without conflicting year evidence.
- Boundary: source/raw DB write scope was `events.time_iso only`; selected serving DB was not mutated; report-local serving candidate DB was written; no graph/vector/production/public pointer, huaidj.club upload, CloudRun/VPS deploy, mini-program upload/review, memory, credential, network/OCR/model, 9router, or D-root action.
- Next resume pointer: `tools\stage7_rewrite\reports\atlas_t5_serving_time_overlay_candidate_20260527\serving_time_overlay_summary.json`.

## 2026-05-27 Atlas T6 Time-Title Exact-Date Recovery + Readback Gate

- `tools\stage7_rewrite\scripts\build_atlas_t6_time_title_exact_date_recovery_packet.py` consumes the bounded T5 time-title recovery queue, extracts exact full-date / relative-post-date / month-day-with-post-date candidates, and writes split review queues for month/day-year, span/range, relative source context, ambiguity, weak date tokens, and source/OCR/manual recovery.
- `tools\stage7_rewrite\scripts\build_atlas_t6_time_title_readback_gate.py` consumes the recovery-ready rows, opens selected serving SQLite read-only, and validates current performance-event and DJ-event rows with batched source-ref readback.
- Regression coverage: `tools\stage7_rewrite\tests\test_build_atlas_t6_time_title_exact_date_recovery_packet.py` and `tools\stage7_rewrite\tests\test_build_atlas_t6_time_title_readback_gate.py`.
- Current real outputs: `reports\ATLAS_T6_TIME_TITLE_EXACT_DATE_RECOVERY_20260527.md`, `reports\ATLAS_T6_TIME_TITLE_READBACK_GATE_20260527.md`, `tools\stage7_rewrite\reports\atlas_t6_time_title_exact_date_recovery_20260527\time_title_exact_date_recovery_summary.json`, `tools\stage7_rewrite\reports\atlas_t6_time_title_readback_gate_20260527\time_title_readback_summary.json`, and `time_title_readback_ready_report_only.jsonl`.
- Counts: recovery input work orders `2000`; candidate-ready rows `78`; exact-full-date ready `75`; relative-post-date ready `2`; month-day-with-post-date ready `1`; month/day-year required `1281`; span/range review `168`; relative-date source-context `352`; ambiguous multiple-date review `13`; weak/false date-token blocked `4`; source/OCR/manual recovery `104`; readback input/readback/ready/blocked `78/78/78/0`; performance-event missing `starts_at` rows covered `412`; DJ-event missing `starts_at` rows covered `3036`; unique event IDs/DJ IDs `412/314`.
- LLM audit: weak numeric labels such as `v2.0` and `20/20` are now blocked; conflicting full-date plus month/day evidence inside a source group is demoted to ambiguity review; the readback builder was optimized from per-source-ref large-table queries to batched `IN (...)` readback after the first real run timed out.
- Boundary: report-only recovery and selected serving SQLite read-only readback; no source/raw DB open/write, serving write/rebuild, graph/vector/public mutation, huaidj.club upload, CloudRun/VPS, mini-program, memory, credential, network/OCR/model, 9router, or D-root scan.
- Next resume pointer: `tools\stage7_rewrite\reports\atlas_t6_time_title_readback_gate_20260527\time_title_readback_ready_report_only.jsonl`.

## 2026-05-27 Atlas T5 Serving City Overlay Local API Package Preflight

- `services\weekly_activity_cloudrun\scripts\atlasServingLocalSmoke.mjs` now includes city event queries for `深圳`, `上海`, `贵阳`, `北京`, and `杭州`, records `citySearchSummary`, and treats top-level `kind: "events"` as event results.
- `tools\stage7_rewrite\scripts\build_atlas_t5_serving_city_overlay_local_api_package_preflight.py` consumes the passing local API/browser smoke, short-city gate summary, and local CloudRun package context evidence to emit a report-only package preflight.
- Regression coverage: `tools\stage7_rewrite\tests\test_build_atlas_t5_serving_city_overlay_local_api_package_preflight.py`.
- Current real outputs: `reports\ATLAS_T5_SERVING_CITY_OVERLAY_LOCAL_API_PACKAGE_PREFLIGHT_20260527.md`, `tools\stage7_rewrite\reports\atlas_t5_serving_city_overlay_local_api_package_preflight_20260527\serving_city_overlay_local_api_package_preflight_summary.json`, `serving_city_overlay_local_api_package_contract.json`, `reports\atlas_serving_city_overlay_local_api_smoke_20260527_0813\api_smoke.json`, `browser_smoke.json`, and `reports\atlas_serving_city_overlay_cloudrun_context_20260527_0816\atlas_serving_sqlite_cloudrun_context.json`.
- Counts: API checks `16/16`; browser checks `5/5`; city event searches `5`; city event result/match rows `40/40`; short-city fallback match rows `12284`; short-city unique terms `24`; package context ready rows `1`; package sidecars copied `2`; CloudRun deploy, huaidj.club upload, public pointer, graph/vector, source/raw, and memory write rows all `0`.
- LLM audit: the first local API smoke failed because the smoke script looked only for `item.type === "event"` while the real API returns event rows as top-level `kind: "events"`; the payload already had exact city matches, so the smoke assertion was fixed and rerun.
- Boundary: report-only/local-only API, browser, and package-context preflight. CloudRun deploy, huaidj.club upload, public pointer mutation, selected serving mutation, serving rebuild, source/raw DB write, graph/vector/public mutation, mini-program upload/review, memory, credential, network/OCR/model, 9router, and D-root scan remain closed.
- Next resume pointer: `tools\stage7_rewrite\reports\atlas_t5_serving_city_overlay_local_api_package_preflight_20260527\serving_city_overlay_local_api_package_preflight_summary.json`.

## 2026-05-27 Atlas T5 Serving City Overlay Short-City Search Gate

- `services\weekly_activity_cloudrun\src\stage7AtlasSqliteStore.mjs` adds a short-CJK/public-city exact `city_text` fallback after empty FTS results. This is intentionally narrower than broad LIKE: it only opens when the query is a public city-as-place label or a 1-2 character CJK normalized label.
- `services\weekly_activity_cloudrun\tests\stage7SqliteLocal.test.mjs` covers short city search rows where FTS rows are absent.
- `tools\stage7_rewrite\scripts\build_atlas_t5_serving_city_overlay_short_city_search_gate.py` consumes the 07:24 city overlay smoke summary and the overlay candidate DB read-only to prove that FTS5 trigram does not serve the 24 short CJK city labels, verify exact `city_text` fallback coverage, and assert service fallback markers.
- Regression coverage: `tools\stage7_rewrite\tests\test_build_atlas_t5_serving_city_overlay_short_city_search_gate.py`.
- Current real outputs: `reports\ATLAS_T5_SERVING_CITY_OVERLAY_SHORT_CITY_SEARCH_GATE_20260527.md`, `tools\stage7_rewrite\reports\atlas_t5_serving_city_overlay_short_city_search_gate_20260527\serving_city_overlay_short_city_search_gate_summary.json`, `serving_city_overlay_short_city_search_contract.json`, `short_city_direct_search_samples.jsonl`, `short_city_term_fallback_status.jsonl`, and `short_city_search_failed_rows.jsonl`.
- Counts: overlay event search rows `12284`; unique city terms `24`; short CJK city terms `24`; direct city fallback match rows `12284`; direct missing/mismatch/text-missing `0/0/0`; FTS city-term match rows `0`; FTS short-city refresh-insufficient rows `12284`; broad LIKE city-term rows `400130`; service fallback markers passed `6/6`.
- LLM audit: the prior "FTS refresh required" gate was directionally useful but technically incomplete because trigram tokenization cannot answer 1-2 character city terms. Exact city evidence is the correct safe fallback.
- Boundary: report-only/read-only candidate DB plus local service/test change; no source/raw DB open/write, selected serving mutation, serving rebuild, graph/vector/public mutation, huaidj.club upload, CloudRun/VPS deploy, mini-program upload/review, memory, credential, network/OCR/model, 9router, or D-root scan.
- Next resume pointer: `tools\stage7_rewrite\reports\atlas_t5_serving_city_overlay_short_city_search_gate_20260527\serving_city_overlay_short_city_search_gate_summary.json`.

## 2026-05-27 Atlas T5 Serving City Overlay Search/Graph Smoke

- `tools\stage7_rewrite\scripts\build_atlas_t5_serving_city_overlay_search_graph_smoke.py` consumes the 07:01 city overlay summary and event search-document rows, opens the report-local overlay candidate DB read-only, and validates direct event search city readback, DJ-event graph coverage, graph-window seeds, metric drift, leak guards, and FTS refresh status.
- Regression coverage: `tools\stage7_rewrite\tests\test_build_atlas_t5_serving_city_overlay_search_graph_smoke.py`.
- Current real outputs: `reports\ATLAS_T5_SERVING_CITY_OVERLAY_SEARCH_GRAPH_SMOKE_20260527.md`, `tools\stage7_rewrite\reports\atlas_t5_serving_city_overlay_search_graph_smoke_20260527\serving_city_overlay_search_graph_smoke_summary.json`, `serving_city_overlay_api_contract.json`, direct search samples, graph samples, failed rows, and FTS status.
- Counts: overlay event search rows checked `12284`; direct city matches `12284`; direct missing/mismatch/text-missing `0/0/0`; graph event rows checked `12284`; DJ-event edges `38103`; unique DJs `5094`; graph window seed rows `5094`; missing graph seeds `0`; metric drift rows `0`; FTS refresh required rows `12284`; FTS city terms requiring refresh `24`.
- LLM audit: the generic serving search/graph health refresh was not precise enough for this overlay. The dedicated smoke binds the exact overlay search rows and turns deferred FTS into an explicit next gate while keeping public deployability false.
- Self-correction: repo-external temp paths are now hash-redacted before outputs are leak-scanned, preventing false local-path hits in tests without weakening production leak checks.
- Boundary: report-only/read-only; no source/raw DB open/write, selected serving mutation, serving rebuild, graph/vector/public mutation, huaidj.club upload, CloudRun/VPS deploy, mini-program upload/review, memory, credential, network/OCR/model, 9router, or D-root scan.
- Next resume pointer: `tools\stage7_rewrite\reports\atlas_t5_serving_city_overlay_search_graph_smoke_20260527\serving_city_overlay_search_graph_smoke_summary.json`.

## 2026-05-27 Atlas T5 City Write Execution + Serving Overlay Candidate

- `tools\stage7_rewrite\scripts\run_atlas_t5_city_write_execution_gate.py` consumes the 04:50 city preflight ready raw rows, rechecks source/raw target provenance and prewrite hashes, then executes a confirmed bounded transaction that updates only `events.city`.
- `tools\stage7_rewrite\scripts\build_atlas_t5_serving_city_overlay_candidate.py` copies the selected serving DB and applies only the verified city overlay to a report-local candidate, preserving table counts and `starts_at` gaps; it deliberately defers full event FTS refresh because trigram FTS row updates are expensive on the full candidate.
- Regression coverage: `tools\stage7_rewrite\tests\test_run_atlas_t5_city_write_execution_gate.py` and `tools\stage7_rewrite\tests\test_build_atlas_t5_serving_city_overlay_candidate.py`.
- Current real outputs: `reports\ATLAS_T5_CITY_WRITE_EXECUTION_GATE_20260527.md`, `reports\ATLAS_T5_SERVING_CITY_OVERLAY_CANDIDATE_20260527.md`, `tools\stage7_rewrite\reports\atlas_t5_city_write_execution_gate_20260527\city_write_execution_summary.json`, and `tools\stage7_rewrite\reports\atlas_t5_serving_city_overlay_candidate_20260527\serving_city_overlay_summary.json`.
- Candidate DB: `reports\atlas_serving_city_overlay_candidate_20260527_0535\atlas_serving.sqlite`.
- Counts: source/raw committed `events.city` rows `15954`; overlay mapped serving rows `50387`; candidate updates `performance_event.city=12284`, `dj_event.city=38103`, `search_document=12284`; city gaps improved `performance_event 132423->120139`, `dj_event 349045->310942`; table counts and `starts_at` gaps preserved; deferred FTS rows `12284`.
- LLM audit: a full source/raw serving rebuild was produced at `reports\atlas_serving_city_write_rebuild_candidate_20260527_0525\atlas_serving.sqlite`, but it is not promotable because it regressed current selected serving counts and `starts_at` coverage. The overlay candidate is the safe next local read-model artifact.
- Boundary: source/raw write scope was `events.city only`; selected serving DB was not mutated; overlay writes only report-local candidate DB; no graph/vector/public/CloudRun/huaidj.club/mini-program/memory/network/OCR/model/9router/D-root action.
- Next resume pointer: `tools\stage7_rewrite\reports\atlas_t5_serving_city_overlay_candidate_20260527\serving_city_overlay_summary.json`.

## 2026-05-27 Atlas T5 City Write Preflight Packet

- `tools\stage7_rewrite\scripts\build_atlas_t5_city_write_preflight_packet.py` consumes deterministic venue-to-city serving candidates, the 04:22 gap summary, explicit source/raw target DB provenance, and the source/raw Atlas SQLite target in read-only mode to emit prewrite hashes, rollback contracts, and postwrite readback requirements for a bounded future `events.city` update.
- Regression coverage: `tools\stage7_rewrite\tests\test_build_atlas_t5_city_write_preflight_packet.py`.
- Current real output: `reports\ATLAS_T5_CITY_WRITE_PREFLIGHT_PACKET_20260527.md`, summary decision `atlas_t5_city_write_preflight_partial_ready_report_only`, leak hits `0/0/0`.
- Output package: `tools\stage7_rewrite\reports\atlas_t5_city_write_preflight_20260527\city_write_preflight_summary.json`, `city_write_preflight_contract.json`, `city_write_preflight_ready_raw_event_rows.jsonl`, `city_write_preflight_serving_candidate_mapped_rows.jsonl`, `city_write_preflight_rollback_contracts.jsonl`, `city_write_preflight_postwrite_readback_contracts.jsonl`, `city_write_preflight_blocked_rows.jsonl`, `city_write_preflight_duplicate_selector_groups.jsonl`, and `city_write_preflight_conflict_groups.jsonl`.
- Counts: input serving city candidates `61266`; mapped serving candidates `50387`; blocked serving candidates `10879`; raw event city update targets `15954`; duplicate selector groups `15954`; conflict groups `0`; rollback/postwrite contracts `15954/15954`.
- LLM audit: direct serving IDs cannot be treated as raw source row IDs. The preflight uses exact normalized title plus conservative venue-family matching with empty raw city, and it fixes a false-positive leak scan on prose containing `confirm token` by scanning only key/value-shaped sensitive fields.
- Boundary: report-only and source/raw target SQLite read-only; no source/raw DB write, serving SQLite write/rebuild, graph/vector/public mutation, huaidj.club upload, mini-program upload/review, memory, credential read, network/OCR/model call, 9router, or D: root scan.
- Next resume pointer: `tools\stage7_rewrite\reports\atlas_t5_city_write_preflight_20260527\city_write_preflight_ready_raw_event_rows.jsonl`.

## 2026-05-27 Atlas T5 Time/City/Venue Gap Closure Packet

- `tools\stage7_rewrite\scripts\build_atlas_t5_time_city_venue_gap_closure_packet.py` opens the selected serving SQLite in read-only mode and emits a report-only gap-closure packet for missing `starts_at`, `city`, and `venue_name` across `performance_event` and `dj_event`.
- Regression coverage: `tools\stage7_rewrite\tests\test_build_atlas_t5_time_city_venue_gap_closure_packet.py`.
- Current real output: `reports\ATLAS_T5_TIME_CITY_VENUE_GAP_CLOSURE_PACKET_20260527.md`, summary decision `atlas_t5_time_city_venue_gap_closure_packet_ready_report_only`, leak hits `0/0/0`.
- Output package: `tools\stage7_rewrite\reports\atlas_t5_time_city_venue_gap_closure_20260527\time_city_venue_gap_closure_summary.json`, `time_city_venue_gap_closure_contract.json`, `time_city_venue_gap_field_rollup.json`, `venue_city_deterministic_candidates.jsonl`, `time_title_recovery_work_orders.jsonl`, `source_ocr_gap_recovery_work_orders.jsonl`, and `leak_scan.json`.
- Counts: performance_event starts_at/city/venue gaps `154804/132423/66616`; dj_event starts_at/city/venue gaps `435186/349045/151231`; deterministic venue-to-city candidates `61266`; time-title recovery work orders `2000`; source/OCR gap work orders `2000`.
- LLM audit: city can be repaired only when `lower(trim(venue_name))` has exactly one city in `dj_venue_rollup`; missing `starts_at` is routed to source/title/OCR recovery because `time_text` alone is not exact-date evidence.
- Boundary: report-only and selected serving SQLite read-only; no source/raw DB open/write, serving SQLite write/rebuild, graph/vector/public mutation, huaidj.club upload, mini-program upload/review, memory, credential read, network/OCR/model call, 9router, or D: root scan.
- Next resume pointer: `tools\stage7_rewrite\reports\atlas_t5_time_city_venue_gap_closure_20260527\venue_city_deterministic_candidates.jsonl`.

## 2026-05-27 Atlas T6 Avatar Binary Storage Provenance Gate

- `tools\stage7_rewrite\scripts\build_atlas_t6_avatar_binary_storage_provenance_gate.py` consumes the 03:37 avatar entity binding ready rows, primary-selection review rows, binding blocked rows, and v4 sidecar provenance metadata to emit a report-only binary/source and storage-target provenance gate.
- Regression coverage: `tools\stage7_rewrite\tests\test_build_atlas_t6_avatar_binary_storage_provenance_gate.py`.
- Current real output: `reports\ATLAS_T6_AVATAR_BINARY_STORAGE_PROVENANCE_GATE_20260527.md`, summary decision `atlas_t6_avatar_binary_storage_provenance_gate_blocked_report_only`, leak hits `0/0/0`.
- Output package: `tools\stage7_rewrite\reports\atlas_t6_avatar_binary_storage_provenance_gate_20260527\avatar_binary_storage_provenance_summary.json`, `avatar_binary_storage_provenance_contract.json`, `avatar_primary_selection_candidates.jsonl`, `avatar_primary_selection_superseded_rows.jsonl`, `avatar_primary_selection_unresolved_rows.jsonl`, `avatar_binary_storage_ready_report_only.jsonl`, `avatar_binary_storage_blocked_rows.jsonl`, `avatar_binding_repair_work_orders.jsonl`, `leak_scan.json`, and summary Markdown.
- Counts: bound input rows `24`; primary avatar candidates/superseded/unresolved `23/1/0`; duplicate primary groups input/resolved `1/1`; binary storage ready/blocked rows `0/23`; binding repair work-order rows `1`; binary-source/storage-target provenance-ready rows `0/0`; binary files scanned/hash rows `0/0`.
- LLM audit: the previous duplicate primary-avatar blocker is now solved deterministically by largest-byte-size selection. The remaining blocker is explicit binary source root, explicit storage target root, and one `DJ HEARTSTRING` serving identity repair.
- Boundary: report-only provenance gate; no binary files opened in the default run, no avatar download/storage write, no source/raw DB open/write, no serving SQLite open/write/rebuild, no graph/vector/public mutation, no huaidj.club upload, no mini-program upload/review, no memory, no credential read, no network/model/OCR call, no 9router, and no D: root scan.
- Next resume pointer: `tools\stage7_rewrite\reports\atlas_t6_avatar_binary_storage_provenance_gate_20260527\avatar_binary_storage_blocked_rows.jsonl`.

## 2026-05-27 Atlas T6 Avatar Entity Binding Gate

- `tools\stage7_rewrite\scripts\build_atlas_t6_avatar_entity_binding_gate.py` consumes the 03:08 storage-ready avatar rows, v4 avatar manifest evidence, and selected serving SQLite read-only to emit a report-only DJ-first Atlas entity binding gate.
- Regression coverage: `tools\stage7_rewrite\tests\test_build_atlas_t6_avatar_entity_binding_gate.py`.
- Current real output: `reports\ATLAS_T6_AVATAR_ENTITY_BINDING_GATE_20260527.md`, summary decision `atlas_t6_avatar_entity_binding_gate_partial_ready_storage_target_blocked_report_only`, leak hits `0/0/0`.
- Output package: `tools\stage7_rewrite\reports\atlas_t6_avatar_entity_binding_gate_20260527\avatar_entity_binding_summary.json`, `avatar_entity_binding_contract.json`, `avatar_entity_binding_ready_report_only.jsonl`, `avatar_entity_binding_blocked_rows.jsonl`, `avatar_primary_selection_review_rows.jsonl`, `leak_scan.json`, and summary Markdown.
- Counts: input storage-ready rows `68`; DJ-first input rows `25`; serving `dj_id` bound rows `24`; binding blocked rows `1`; unique bound serving DJ IDs `23`; serving search/graph readback rows `24/24`; duplicate serving-DJ avatar groups `1`; primary avatar selection review rows `2`; binary-source/storage-target provenance-ready rows `0/0`.
- LLM audit: DJ-first binding is mostly ready, but storage/public display remains blocked by explicit target provenance, duplicate primary-avatar policy, and one missing binding.
- Boundary: selected serving SQLite read-only binding only; no avatar binary download/storage write, no source/raw DB open/write, no serving SQLite write/rebuild, no graph/vector/public mutation, no huaidj.club upload, no mini-program upload/review, no memory, no credential read, no network/model/OCR call, no 9router, and no D: root scan.
- Next resume pointer: `tools\stage7_rewrite\reports\atlas_t6_avatar_entity_binding_gate_20260527\avatar_entity_binding_ready_report_only.jsonl`.

## 2026-05-27 Atlas T6 Avatar Storage Contract Gate

- `tools\stage7_rewrite\scripts\build_atlas_t6_avatar_storage_contract_gate.py` consumes the 02:44 avatar/media recovery contract rows and emits a report-only storage/display contract gate for hash-addressable avatar artifacts.
- Regression coverage: `tools\stage7_rewrite\tests\test_build_atlas_t6_avatar_storage_contract_gate.py`.
- Current real output: `reports\ATLAS_T6_AVATAR_STORAGE_CONTRACT_GATE_20260527.md`, summary decision `atlas_t6_avatar_storage_contract_gate_ready_report_only`, failed checks `[]`, leak hits `0/0/0`.
- Output package: `tools\stage7_rewrite\reports\atlas_t6_avatar_storage_contract_gate_20260527\avatar_storage_contract_summary.json`, `avatar_storage_contract.json`, `avatar_storage_contract_ready_report_only.jsonl`, `avatar_storage_contract_blocked_rows.jsonl`, `leak_scan.json`, and summary Markdown.
- Counts: input avatar rows `68`; storage-contract ready/blocked rows `68/0`; DJ-first/non-DJ ready rows `25/43`; entity-kind split `dj=25`, `venue=31`, `label=10`, `missing_rollup=2`; platform split `youtube=47`, `instagram=19`, `soundcloud=2`.
- LLM audit: avatar discovery is no longer the blocker. The remaining gate is binding and storage provenance: DJ-first rows must map to Atlas `dj_id`, storage/binary targets must be explicit, and checksum readback plus serving/public avatar smoke must pass before any display field opens.
- Boundary: report-local storage contract only; no avatar binary download/storage write, no source/raw DB open/write, no serving SQLite open/write/rebuild, no graph/vector/public mutation, no huaidj.club upload, no mini-program upload/review, no memory, no credential read, no network/model/OCR call, no 9router, and no D: root scan.
- Next resume pointer: `tools\stage7_rewrite\reports\atlas_t6_avatar_storage_contract_gate_20260527\avatar_storage_contract_ready_report_only.jsonl`.

## 2026-05-27 Atlas T6 Avatar/Media Recovery Packet

- `tools\stage7_rewrite\scripts\build_atlas_t6_avatar_media_recovery_packet.py` consumes the v4 hash/redacted sidecar manifest plus current rendered-UI, old validation, and completion-rollup evidence to emit a report-only avatar/media recovery contract.
- Regression coverage: `tools\stage7_rewrite\tests\test_build_atlas_t6_avatar_media_recovery_packet.py`.
- Current real output: `reports\ATLAS_T6_AVATAR_MEDIA_RECOVERY_PACKET_20260527.md`, summary decision `atlas_t6_avatar_media_recovery_ready_report_only`, failed checks `[]`, leak hits `0/0/0`.
- Output package: `tools\stage7_rewrite\reports\atlas_t6_avatar_media_recovery_packet_20260527\avatar_media_recovery_summary.json`, `avatar_media_recovery_contract.json`, `avatar_media_recovery_work_orders.jsonl`, split JSONL rows, leak scan, and summary Markdown.
- Counts: avatar artifacts input/hash-addressable/DJ-first/non-DJ/missing-rollup `68/68/25/41/2`; media signal rollups total/DJ-first `74/25`; old validation avatar actual/hash-ready/blocked `2/0/2`; completion rollup DJ avatar/media missing `53,555/53,555`.
- LLM audit: stale SSOT was hiding the v4 sidecar avatar evidence. The script keeps all raw URL/path fields out of outputs and routes storage, DJ binding, non-DJ scope, missing-rollup, and public-serving-field gates separately.
- Boundary: report-local hash/redacted planning only; no source/raw DB open/write, no serving SQLite open/write/rebuild, no graph/vector/public mutation, no huaidj.club upload, no mini-program upload/review, no memory, no credential read, no network/model call, no 9router, and no D: root scan.
- Next resume pointer: `tools\stage7_rewrite\reports\atlas_t6_avatar_media_recovery_packet_20260527\avatar_media_recovery_work_orders.jsonl`.

## 2026-05-27 Atlas T5/T6 Sidecar Social Read-Model Rendered UI Smoke

- `tools\stage7_rewrite\scripts\build_atlas_t6_sidecar_social_read_model_rendered_ui_smoke.py` consumes the corrected 02:08 social read-model UI workbench contract and emits a report-local static rendered UI fixture, graph-preview elements, rendered samples, and route-panel smoke contract.
- Regression coverage: `tools\stage7_rewrite\tests\test_build_atlas_t6_sidecar_social_read_model_rendered_ui_smoke.py`.
- Updated upstream builder: `tools\stage7_rewrite\scripts\build_atlas_t6_sidecar_social_read_model_ui_integration_review.py` now separates `dj_social_card` and `platform_filter` samples instead of rendering platform filters as blank DJ cards.
- Current real output: `reports\ATLAS_T5_T6_SIDECAR_SOCIAL_READ_MODEL_RENDERED_UI_SMOKE_20260527.md`, summary decision `atlas_t6_sidecar_social_read_model_rendered_ui_smoke_ready_report_only`, failed checks `[]`, leak hits `0/0/0`.
- Output package: `tools\stage7_rewrite\reports\atlas_t6_sidecar_social_read_model_rendered_ui_smoke_t5_t6_20260527\social_read_model_rendered_ui_smoke_summary.json`, `social_read_model_rendered_ui_contract.json`, `social_read_model_rendered_graph_elements.json`, `social_read_model_rendered_ui_samples.jsonl`, `social_read_model_rendered_ui_fixture.html`, and summary Markdown.
- Counts: workbench sample/platform-filter/blank rows `12/12/0`; rendered route panels/sample cards `5/12`; graph preview elements/nodes/edges `75/38/37`; social/profile/outlink rows `18,710/15,715/2,995`.
- Boundary: report-local static UI fixtures only; no source/raw DB open/write, no serving SQLite open/write/rebuild, no graph/vector/public mutation, no huaidj.club upload, no mini-program upload/review, no memory, no credential read, no network/model call, no 9router, and no D: root scan.
- Next resume pointer: `tools\stage7_rewrite\reports\atlas_t6_sidecar_social_read_model_rendered_ui_smoke_t5_t6_20260527\social_read_model_rendered_ui_contract.json`.

## 2026-05-27 Atlas T5/T6 Sidecar Social Read-Model UI Integration Review

- `tools\stage7_rewrite\scripts\build_atlas_t6_sidecar_social_read_model_ui_integration_review.py` consumes the 01:56 consumer contract and emits the report-local UI/API workbench contract for the DJ-first social/profile/outlink read-model lane.
- Regression coverage: `tools\stage7_rewrite\tests\test_build_atlas_t6_sidecar_social_read_model_ui_integration_review.py`.
- Current real output: `reports\ATLAS_T5_T6_SIDECAR_SOCIAL_READ_MODEL_UI_INTEGRATION_REVIEW_20260527.md`, summary decision `atlas_t6_sidecar_social_read_model_ui_integration_review_ready_report_only`, failed checks `[]`, leak hits `0/0/0`.
- Output package: `tools\stage7_rewrite\reports\atlas_t6_sidecar_social_read_model_ui_integration_review_t5_t6_20260527\social_read_model_ui_integration_review_summary.json`, `social_read_model_ui_workbench_contract.json`, `social_read_model_ui_workbench_sections.json`, `social_read_model_ui_route_checks.jsonl`, and summary Markdown.
- Self-correction: the regenerated workbench records `sample_cards=12`, `platform_filter_samples=12`, and `blank_sample_cards=0` after fixing the platform-filter sample bug.
- Boundary: report-local UI workbench contract only; no source/raw DB open/write, no serving SQLite open/write/rebuild, no graph/vector/public mutation, no huaidj.club upload, no mini-program upload/review, no memory, no credential read, no network/model call, no 9router, and no D: root scan.
- Next resume pointer: `tools\stage7_rewrite\reports\atlas_t6_sidecar_social_read_model_ui_integration_review_t5_t6_20260527\social_read_model_ui_workbench_contract.json`.

## 2026-05-27 Atlas T5/T6 Sidecar Social Read-Model Consumer Smoke

- `tools\stage7_rewrite\scripts\build_atlas_t6_sidecar_social_read_model_consumer_smoke.py` consumes the 2026-05-27 social read-model candidate manifest and validates local consumer/UI route contracts, detail/search/graph subject alignment, platform facets, samples, UI filter state, write guards, and leak guards.
- Regression coverage: `tools\stage7_rewrite\tests\test_build_atlas_t6_sidecar_social_read_model_consumer_smoke.py`.
- Current real output: `reports\ATLAS_T5_T6_SIDECAR_SOCIAL_READ_MODEL_CONSUMER_SMOKE_20260527.md`, summary decision `atlas_t6_sidecar_social_read_model_consumer_smoke_ready_report_only`, failed checks `[]`, leak hits `0/0/0`.
- Output package: `tools\stage7_rewrite\reports\atlas_t6_sidecar_social_read_model_consumer_smoke_t5_t6_20260527\social_read_model_consumer_smoke_summary.json`, `social_read_model_consumer_contract.json`, `social_read_model_consumer_route_smoke.json`, `social_read_model_consumer_samples.jsonl`, `social_read_model_ui_filter_state.json`, and `social_read_model_consumer_smoke_summary.md`.
- Counts: detail/search/graph rows `1,975/1,975/1,975`; platform facet rows `122`; consumer sample rows `24`; distinct search platforms/cities `95/23`; social/profile/outlink rows `18,710/15,715/2,995`.
- LLM audit: the 01:30 candidate was valid but not yet consumer-shaped. This builder proves local UI/API contract readiness while leaving persistence/public gates closed.
- Self-correction: temp report paths outside the repo now render as filenames only to avoid false leak hits; safe human platform labels with spaces/brackets are accepted while URL/path/credential-shaped labels still block.
- Boundary: report-local consumer fixtures only; no source/raw DB open/write, no serving SQLite open/write/rebuild, no graph/vector/public mutation, no huaidj.club upload, no mini-program upload/review, no memory, no credential read, no network/model call, no 9router, and no D: root scan.
- Next resume pointer: `tools\stage7_rewrite\reports\atlas_t6_sidecar_social_read_model_consumer_smoke_t5_t6_20260527\social_read_model_consumer_contract.json`.

## 2026-05-27 Atlas T5/T6 Sidecar Social Read-Model Candidate

- `tools\stage7_rewrite\scripts\build_atlas_t6_sidecar_social_read_model_candidate.py` now consumes both the 2026-05-27 social overlay persistence contract and the 2026-05-26 read-only attach API contract to emit report-local social API/search/graph read-model fixtures.
- Regression coverage: `tools\stage7_rewrite\tests\test_build_atlas_t6_sidecar_social_read_model_candidate.py`.
- Current real output: `reports\ATLAS_T5_T6_SIDECAR_SOCIAL_READ_MODEL_CANDIDATE_20260527.md`, summary decision `atlas_t6_sidecar_social_read_model_candidate_ready_report_only`, failed checks `[]`, leak hits `0/0/0`.
- Output package: `tools\stage7_rewrite\reports\atlas_t6_sidecar_social_read_model_candidate_t5_t6_20260527\social_read_model_candidate_summary.json`, `social_read_model_candidate_manifest.json`, `social_overview_response.json`, `dj_social_detail_responses.jsonl`, `social_search_index.jsonl`, `graph_social_overlays.jsonl`, `social_platform_facet_responses.jsonl`, `social_read_model_route_smoke.json`, and `social_read_model_candidate_summary.md`.
- Counts: detail/search/graph rows `1,975/1,975/1,975`; platform facet rows `122`; platform-host rows `2,024`; social/profile/outlink rows `18,710/15,715/2,995`; route smoke `ok=true`; persistence-contract alignment `ok=true`.
- LLM audit: the stale 2026-05-26-only default path is fixed; the builder now treats the 2026-05-27 persistence contract as a hard gate and emits explicit prewrite, rollback, and postwrite requirements for any future derived serving candidate.
- Self-correction: leak scanning now allows zero-valued metric labels such as `local_secret_path` only as safe metric keys, while still blocking credential-shaped content.
- Boundary: report-local fixtures only; no source/raw DB open/write, no serving SQLite open/write/rebuild, no graph/vector/public mutation, no huaidj.club upload, no mini-program upload/review, no memory, no credential read, no 9router, and no D: root scan.
- Next resume pointer: `tools\stage7_rewrite\reports\atlas_t6_sidecar_social_read_model_candidate_t5_t6_20260527\social_read_model_candidate_manifest.json`.

## 2026-05-27 Atlas T5/T6 Sidecar Overlay Persistence Decision

- `tools\stage7_rewrite\scripts\build_atlas_t6_sidecar_overlay_persistence_decision.py` consumes the DJ completion work-order file, the report-local social overlay SQLite, the selected serving SQLite, and the source/raw schema snapshot, all as read-only inputs, to produce the attach-only/read-model persistence decision packet.
- Regression coverage: `tools\stage7_rewrite\tests\test_build_atlas_t6_sidecar_overlay_persistence_decision.py`.
- Current real output: `reports\ATLAS_T5_T6_SIDECAR_OVERLAY_PERSISTENCE_DECISION_20260527.md`, summary decision `atlas_t6_sidecar_overlay_persistence_attach_only_ready_report_only`, failed checks `[]`, leak hits `0/0/0`.
- Output package: `tools\stage7_rewrite\reports\atlas_t6_sidecar_overlay_persistence_decision_t5_t6_20260527\social_overlay_persistence_summary.json`, `social_overlay_persistence_contract.json`, `social_overlay_attach_only_ready_report_only.jsonl`, `social_overlay_persistence_work_orders.jsonl`, `social_overlay_persistence_blocked_rows.jsonl`, `leak_scan.json`, and `social_overlay_persistence_summary.md`.
- Counts: overlay entities/links/profile/outlink `1,975/18,710/15,715/2,995`; platforms/hosts `122/1,961`; selected serving profile/search/graph/event/relation joins `1,975/1,975/1,975/1,975/1,946`; duplicate candidate/selector/link-without-rollup/bad-kind rows `0/0/0/0`; source/raw and selected serving native social tables `0/0`.
- LLM audit: current product-safe decision is attach-only read model. A persistent social field/table path must be a separate derived serving candidate or source/raw schema migration gate with prewrite, rollback, postwrite readback, and FTS consistency if social text is added to search.
- Boundary: report-only read-only decision packet; no source/raw DB open/write, selected serving mutation/rebuild, graph/vector/public mutation, huaidj.club upload, mini-program upload/review, memory, credential read, 9router, or D: root scan.
- Next resume pointer: `tools\stage7_rewrite\reports\atlas_t6_sidecar_overlay_persistence_decision_t5_t6_20260527\social_overlay_persistence_work_orders.jsonl`.

## 2026-05-27 Atlas T7 HUAIDJ Root Graph Home / Turnstile SSOT Sync

- `reports\ATLAS_T7_HUAIDJ_ROOT_GRAPH_HOME_SSOT_SYNC_20260527.md` and `tools\stage7_rewrite\reports\atlas_t7_huaidj_root_graph_home_ssot_sync_20260527\root_graph_home_ssot_sync_summary.json` record the SSOT reconciliation after `docs\current-runtime.md` advanced to the 00:48 Atlas Turnstile failure-handling fix and 00:39 HUAIDJ root Atlas graph home boundary.
- Decision `atlas_t7_huaidj_root_graph_home_turnstile_ssot_sync_ready_report_only`, failed checks `[]`, SSOT drift resolved rows `1`, current public entry `https://huaidj.club/`, protected graph entry `https://atlas.huaidj.club/atlas/graph`, Turnstile failure handling fixed remote-effective `true`, leak hits `0/0/0`.
- This is docs/status evidence only; it adds no new runtime code and does not repeat remote upload or mutate source/raw DB, serving SQLite, Neo4j, Qdrant, production SQLite, public pointer, CloudRun, mini-program, memory, credentials, 9router, or D: roots.
- Next resume pointer: `https://huaidj.club/` for human Turnstile/readability checks; local data-quality work continues from `tools\stage7_rewrite\reports\atlas_dj_completion_overlay_rollup_t5_t6_20260527\dj_completion_next_work_orders.jsonl`.

## 2026-05-27 Atlas T5/T6 DJ Completion Overlay Rollup

- `tools\stage7_rewrite\scripts\build_atlas_dj_completion_overlay_rollup.py` consumes existing redacted/report-local DJ completion, sidecar manifest, overlay attach, UI integration, and SSOT boundary artifacts to produce a report-only completion/gap/work-order rollup.
- Regression coverage: `tools\stage7_rewrite\tests\test_build_atlas_dj_completion_overlay_rollup.py`.
- Current real output: `reports\ATLAS_T5_T6_DJ_COMPLETION_OVERLAY_ROLLUP_20260527.md`, summary decision `atlas_dj_completion_overlay_rollup_ready_report_only`, failed checks `[]`, leak hits `0/0/0`.
- Output package: `tools\stage7_rewrite\reports\atlas_dj_completion_overlay_rollup_t5_t6_20260527\dj_completion_overlay_rollup_summary.json`, `dj_completion_overlay_rollup.json`, `dj_completion_next_work_orders.jsonl`, and `dj_completion_overlay_rollup_summary.md`.
- Counts: DJ profiles / performance events / DJ-event edges / directed relations / search docs / graph windows `53,555/508,049/1,285,827/701,396/590,927/53,555`; deltas vs base `+96/+28/+399/+1,596/+124/+96`; WSL sidecar processed/remaining `246,024/0`; overlay social entities `1,975`; overlay link/profile/outlink rows `18,710/15,715/2,995`; UI elements/nodes/edges `136/34/102`; work orders `5`.
- Open gaps: DJ avatar/media fields remain `53,555/53,555` empty; performance_event starts_at/city/venue gaps `154,804/132,423/66,616`; dj_event starts_at/city/venue gaps `435,186/349,045/151,231`.
- LLM audit: the graph is now large and DJ-first, but "full Atlas production" still needs social overlay persistence, avatar/media recovery, and time/city/venue gap closure. The script also caught SSOT drift where current-runtime/Stage7 SSOT had the 00:10 protected graph UI public upload while several indexes still pointed at 23:45 local-only evidence.
- Boundary: report-only rollup; no source/raw DB open/mutation, serving open/write/rebuild, graph/vector/public mutation, huaidj.club upload, mini-program upload/review, memory, credential read, 9router, or D: root scan.
- Next resume pointer: `tools\stage7_rewrite\reports\atlas_dj_completion_overlay_rollup_t5_t6_20260527\dj_completion_next_work_orders.jsonl`.

## 2026-05-26 Atlas T5/T6 Sidecar Overlay UI Integration Smoke

- `tools\stage7_rewrite\scripts\build_atlas_t6_sidecar_overlay_ui_integration_smoke.py` consumes the report-local overlay UI contract and validates local graph UI view-model integration without opening source/raw DB or serving SQLite.
- Regression coverage: `tools\stage7_rewrite\tests\test_build_atlas_t6_sidecar_overlay_ui_integration_smoke.py`.
- Current real output: `reports\ATLAS_T5_T6_SIDECAR_OVERLAY_UI_INTEGRATION_SMOKE_20260526.md`, summary decision `atlas_t6_sidecar_overlay_ui_integration_smoke_ready_report_only`, failed checks `[]`, leak hits `0/0/0`.
- Output package: `tools\stage7_rewrite\reports\atlas_t6_sidecar_overlay_ui_integration_smoke_t5_t6_20260526\overlay_social_ui_integration_contract.json`, `overlay_social_cytoscape_elements.json`, `overlay_social_ui_filter_state.json`, `overlay_social_ui_integration_samples.jsonl`, `overlay_social_ui_integration_smoke_summary.json`, and `overlay_social_ui_integration_smoke_summary.md`.
- Counts: attach-ready/blocked entity rows `1,975/0`; Cytoscape elements/nodes/edges `136/34/102`; DJ/platform/city nodes `8/20/6`; platform/city edges `94/8`; detail/graph/integration sample rows `8/8/8`; platform facets `12`; overlay link/profile/outlink rows `18,710/15,715/2,995`; serving event/relation edges `436,835/364,868`.
- Self-correction: detail-only platforms absent from top platform facets are now recorded as sample-only platforms; unsafe URL-like platform labels still block.
- Boundary: report-only local UI integration smoke; no source/raw DB open/mutation, serving open/write/rebuild, graph/vector/public mutation, huaidj.club upload, mini-program upload/review, memory, credential read, 9router, or D: root scan.
- Next resume pointer: `tools\stage7_rewrite\reports\atlas_t6_sidecar_overlay_ui_integration_smoke_t5_t6_20260526\overlay_social_ui_integration_contract.json`.

## 2026-05-26 Atlas T5/T6 Sidecar Overlay Local API Consumer Smoke

- `tools\stage7_rewrite\scripts\build_atlas_t6_sidecar_overlay_local_api_consumer_smoke.py` consumes the report-local overlay local API candidate manifest and response fixtures, validates consumer/UI/API route contracts, and emits a report-only UI contract without opening source/raw DB or serving SQLite.
- Regression coverage: `tools\stage7_rewrite\tests\test_build_atlas_t6_sidecar_overlay_local_api_consumer_smoke.py`.
- Current real output: `reports\ATLAS_T5_T6_SIDECAR_OVERLAY_LOCAL_API_CONSUMER_SMOKE_20260526.md`, summary decision `atlas_t6_sidecar_overlay_local_api_consumer_smoke_ready_report_only`, failed checks `[]`, leak hits `0/0/0`.
- Output package: `tools\stage7_rewrite\reports\atlas_t6_sidecar_overlay_local_api_consumer_smoke_t5_t6_20260526\overlay_social_ui_contract.json`, `overlay_social_consumer_route_smoke.json`, `overlay_social_consumer_samples.jsonl`, `overlay_social_local_api_consumer_smoke_summary.json`, and `overlay_social_local_api_consumer_smoke_summary.md`.
- Counts: route contracts `5`; overview/detail/search/platform/graph rows `1/24/1/12/8`; search item rows `12`; graph sample DJ rows `8`; attach-ready/blocked entity rows `1,975/0`; platform-host rows `2,024`; distinct platforms/hosts `122/1,961`; overlay link/profile/outlink rows `18,710/15,715/2,995`; serving event/relation edges `436,835/364,868`.
- Self-corrections: zero-valued outlink totals are now parsed as valid counts instead of missing fields; safe colon host tokens such as `facebook:http:` are allowed without allowing raw URL/path/credential shapes.
- Boundary: report-only local UI/API consumer smoke; no source/raw DB open/mutation, serving open/write/rebuild, graph/vector/public mutation, huaidj.club upload, mini-program upload/review, memory, credential read, 9router, or D: root scan.
- Next resume pointer: `tools\stage7_rewrite\reports\atlas_t6_sidecar_overlay_local_api_consumer_smoke_t5_t6_20260526\overlay_social_ui_contract.json`.

## 2026-05-26 Atlas T5/T6 Sidecar Overlay Local API Candidate

- `tools\stage7_rewrite\scripts\build_atlas_t6_sidecar_overlay_local_api_candidate.py` consumes the report-local overlay serving attach API contract and emits public-safe local API/read-model response fixtures for DJ social/profile/outlink rows without opening source/raw DB or serving SQLite.
- Regression coverage: `tools\stage7_rewrite\tests\test_build_atlas_t6_sidecar_overlay_local_api_candidate.py`.
- Current real output: `reports\ATLAS_T5_T6_SIDECAR_OVERLAY_LOCAL_API_CANDIDATE_20260526.md`, summary decision `atlas_t6_sidecar_overlay_local_api_candidate_ready_report_only`, failed checks `[]`, leak hits `0/0/0`.
- Output package: `tools\stage7_rewrite\reports\atlas_t6_sidecar_overlay_local_api_candidate_t5_t6_20260526\overlay_social_local_api_candidate_manifest.json`, `overlay_social_overview_response.json`, `overlay_social_detail_responses.jsonl`, `overlay_social_search_response.json`, `overlay_social_platform_responses.jsonl`, `overlay_social_graph_responses.jsonl`, `overlay_social_local_api_candidate_summary.json`, and `overlay_social_local_api_candidate_summary.md`.
- Counts: route contracts `5`; overview/detail/search/platform/graph responses `1/24/1/12/8`; attach-ready/blocked entity rows `1,975/0`; platform-host rows `2,024`; distinct platforms/hosts `122/1,961`; overlay link/profile/outlink rows `18,710/15,715/2,995`; serving event/relation edges `436,835/364,868`.
- Self-correction: first real run over-blocked detail rows because `write_status` can live inside `body` rather than top-level. The builder now accepts both forms and tests body-only detail report status.
- Boundary: report-only local API/read-model candidate; no source/raw DB open/mutation, serving open/write/rebuild, graph/vector/public mutation, huaidj.club upload, mini-program upload/review, memory, credential read, 9router, or D: root scan.
- Next resume pointer: `tools\stage7_rewrite\reports\atlas_t6_sidecar_overlay_local_api_candidate_t5_t6_20260526\overlay_social_local_api_candidate_manifest.json`.

## 2026-05-26 Atlas T5/T6 Sidecar Overlay Serving Attach Smoke

- `tools\stage7_rewrite\scripts\build_atlas_t6_sidecar_overlay_serving_attach_smoke.py` opens selected serving SQLite read-only, attaches the report-local sidecar overlay SQLite read-only, and emits a report-only serving/search/graph/API attach contract for DJ social/profile/outlink rows.
- Regression coverage: `tools\stage7_rewrite\tests\test_build_atlas_t6_sidecar_overlay_serving_attach_smoke.py`.
- Current real output: `reports\ATLAS_T5_T6_SIDECAR_OVERLAY_SERVING_ATTACH_SMOKE_20260526.md`, summary decision `atlas_t6_sidecar_overlay_serving_attach_smoke_ready_report_only`, failed checks `[]`, leak hits `0/0/0`.
- Output package: `tools\stage7_rewrite\reports\atlas_t6_sidecar_overlay_serving_attach_smoke_t5_t6_20260526\overlay_social_api_contract.json`, `overlay_entity_attach_rows.jsonl`, `overlay_entity_attach_ready_report_only.jsonl`, `overlay_entity_attach_blocked_rows.jsonl`, `overlay_platform_rollup.jsonl`, `overlay_social_api_detail_samples.jsonl`, `overlay_serving_schema_snapshot.json`, and `overlay_serving_attach_smoke_summary.json`.
- Counts: overlay link/rollup/entity rows `18,710/1,975/1,975`; profile/outlink rows `15,715/2,995`; serving `dj_profile/search_document/graph_window` matches `1,975/1,975/1,975`; serving event/relation edges for social entities `436,835/364,868`; attach-ready/blocked entity rows `1,975/0`; duplicate selector groups `0`; links without rollup `0`.
- Self-correction: first real attach attempts were too slow over the multi-GB serving DB. The builder now avoids full serving `quick_check` and uses batched Python `IN` queries instead of per-entity/full-table SQLite plans.
- Boundary: report-only read-only attach; no source/raw DB open/mutation, serving rebuild/write, graph/vector/public mutation, huaidj.club upload, mini-program upload/review, memory, credential read, 9router, or D: root scan.
- Next resume pointer: `tools\stage7_rewrite\reports\atlas_t6_sidecar_overlay_serving_attach_smoke_t5_t6_20260526\overlay_social_api_contract.json`.

## 2026-05-26 Atlas T5/T6 Sidecar New DB Overlay

- `tools\stage7_rewrite\scripts\build_atlas_t6_sidecar_new_db_overlay.py` consumes the T5/T6 sidecar validation gate, opens the explicit source/raw target DB read-only, redacts sensitive schema identifiers, and writes a report-local SQLite overlay for DJ social profile/outlink rows.
- Regression coverage: `tools\stage7_rewrite\tests\test_build_atlas_t6_sidecar_new_db_overlay.py`.
- Current real output: `reports\ATLAS_T5_T6_SIDECAR_NEW_DB_OVERLAY_20260526.md`, summary decision `atlas_t6_sidecar_new_atlas_overlay_db_built_local_only`, failed checks `[]`, leak hits `0/0/0`.
- Output package: `tools\stage7_rewrite\reports\atlas_t6_sidecar_new_db_overlay_t5_t6_20260526\atlas_t6_sidecar_social_overlay.sqlite`, `prewrite_schema_snapshot.json`, `postwrite_readback.json`, `rollback_contract.json`, `validation_blockers.jsonl`, and `sidecar_new_db_overlay_summary.json`.
- Counts: input merge-precheck-ready rows `18,710`; profile/outlink rows `15,715/2,995`; overlay link/rollup/entity rows `18,710/1,975/1,975`; duplicate selector rows `0`; write-guard-open rows `0`.
- Self-correction: scanner now distinguishes sensitive schema/key names from legitimate artist/domain strings containing `Secret`; schema identifiers such as `source_token_hash` are hash-redacted in outputs.
- Boundary: report-local overlay SQLite write only; no source/raw mutation, serving rebuild/write, graph/vector/public mutation, huaidj.club upload, mini-program upload/review, memory, credential read, 9router, or D: root scan.
- Next resume pointer: `tools\stage7_rewrite\reports\atlas_t6_sidecar_new_db_overlay_t5_t6_20260526\atlas_t6_sidecar_social_overlay.sqlite`.

## 2026-05-26 Atlas T5/T6 Sidecar Manifest Validation Gate

- `tools\stage7_rewrite\scripts\build_atlas_t6_sidecar_manifest_validation_gate.py` validates the T6 WSL2 hash/redacted sidecar manifest against the selected Atlas serving DB in read-only mode before any new Atlas DB merge gate. It checks schema/count integrity, write guards, redaction, duplicate candidate/canonical URL-key drift, serving DJ entity coverage, entity rollup consistency, identity review blockers, avatar blockers, and upstream blocker reasons.
- Regression coverage: `tools\stage7_rewrite\tests\test_build_atlas_t6_sidecar_manifest_validation_gate.py`.
- Current real output: `reports\ATLAS_T5_T6_SIDECAR_MANIFEST_VALIDATION_GATE_20260526.md`, summary decision `atlas_t6_sidecar_manifest_validation_gate_ready_report_only`, failed checks `[]`, leak hits `0/0/0`.
- Output package: `tools\stage7_rewrite\reports\atlas_t6_sidecar_manifest_validation_gate_t5_t6_20260526\merge_contract.json`, `candidate_validation_rows.jsonl`, `merge_precheck_ready_candidates.jsonl`, `merge_review_required_candidates.jsonl`, `entity_validation_rollups.jsonl`, `avatar_validation_rows.jsonl`, `validation_blockers.jsonl`, `leak_scan.json`, and `sidecar_manifest_validation_summary.json`.
- Counts: candidates/entity rollups/avatar/upstream-blocked rows `18,741/1,986/2/12,260`; merge-precheck-ready rows `18,710`; review-required identity rows `31`; validation-blocked rows `0`; duplicate candidate/url-key groups `0/0`; missing serving entity refs `0`; avatar hash-ready/blocked rows `0/2`.
- Self-correction: focused tests caught that input payload leaks must be scanned before writing sanitized validation rows, not only after row normalization.
- Boundary: report-only validation; no source/raw write, serving rebuild/write, graph/vector/public mutation, huaidj.club upload, mini-program upload/review, memory, credential read, 9router, or D: root scan.
- Next resume pointer: `tools\stage7_rewrite\reports\atlas_t6_sidecar_manifest_validation_gate_t5_t6_20260526\merge_contract.json`.

## 2026-05-26 Atlas T6 Sidecar Redacted Manifest

- `tools\stage7_rewrite\scripts\build_atlas_t6_sidecar_redacted_manifest.py` converts the WSL2 `claude-deepseek-pro` scratch SQLite sidecar into a T6->T5 hash/redacted manifest package. It copies the UNC scratch DB to a temporary local snapshot for read-only access, joins candidates to the selected serving DB by normalized DJ names, emits only hashed/redacted URL/path references, and keeps all write/public/memory guards false.
- Regression coverage: `tools\stage7_rewrite\tests\test_build_atlas_t6_sidecar_redacted_manifest.py`.
- Current real output: `reports\ATLAS_T6_SIDECAR_REDACTED_MANIFEST_20260526.md`, summary decision `atlas_t6_sidecar_redacted_manifest_ready_report_only`, failed checks `[]`, leak hits `0/0/0`.
- Input scratch counts: `dj_social_profiles=24,184`, `dj_outlinks=8,300`, `dj_identity_candidates=184`, `dj_avatars=2`.
- Output counts: joined candidates `18,741`, entity rollups `1,986`, avatar artifacts `2`, blocked rows `12,260`.
- Self-correction: real sidecar rows contained non-numeric confidence labels and malformed pseudo-URLs; the builder now handles both deterministically instead of crashing or leaking raw values.
- Boundary: report-only sidecar manifest; no source/raw write, serving rebuild/write, graph/vector/public mutation, huaidj.club upload, mini-program upload/review, memory, credential read, 9router, or D: root scan.
- Next resume pointer: `tools\stage7_rewrite\reports\atlas_t6_sidecar_redacted_manifest_20260526\manifest.json`.

## 2026-05-26 Atlas T5/T6 DJ Completion Effect Audit

- `tools\stage7_rewrite\scripts\build_atlas_dj_completion_effect_audit.py` audits the selected DJ-first serving candidate against its base, opens the explicit source/raw DB read-only for source counts, inspects the WSL2 sidecar scratch SQLite through a temporary read-only snapshot, and emits a report-only completion/gap/contract packet.
- Regression coverage: `tools\stage7_rewrite\tests\test_build_atlas_dj_completion_effect_audit.py`.
- Current real output: `reports\ATLAS_T5_T6_DJ_COMPLETION_EFFECT_AND_SIDECAR_CONTRACT_20260526.md`, summary decision `atlas_dj_completion_effect_audit_ready_report_only`, failed checks `[]`, leak hits `0/0/0`.
- Candidate effect: selected serving candidate has DJ profiles / performance events / DJ-event edges / directed relations / search docs / graph windows `53,555/508,049/1,285,827/701,396/590,927/53,555`, deltas vs base `+96/+28/+399/+1,596/+124/+96`.
- Open gaps: avatar/media fields remain empty; starts_at/city/venue gaps remain material for `performance_event` and `dj_event`.
- Sidecar contract: WSL scratch DB currently has `dj_social_profiles=24,184`, `dj_outlinks=8,300`, `dj_identity_candidates=184`, `dj_avatars=2`, but URL and `local_path` columns are present; T6 must emit hashed/redacted manifest files before T5 merge/new-DB gates.
- Boundary: report-only audit; no source/raw write, serving rebuild/write, graph/vector/public mutation, huaidj.club upload, mini-program upload/review, memory, credential read, 9router, or D: root scan.
- Next resume pointer: `tools\stage7_rewrite\reports\atlas_dj_completion_effect_audit_t5_t6_20260526\dj_completion_gap_register.jsonl`.

## 2026-05-26 Atlas Q6/T5 Manual Participant Remaining Identity Readback Gate

- `tools\stage7_rewrite\scripts\build_atlas_social_manual_participant_event_identity_readback_gate.py` now also consumes the 15:41 remaining-identity readback candidates, opens selected serving SQLite read-only, and emits a report-only readback gate under `tools\stage7_rewrite\reports\atlas_social_manual_participant_remaining_identity_readback_gate_q6_20260526`.
- Regression coverage: `tools\stage7_rewrite\tests\test_build_atlas_social_manual_participant_event_identity_readback_gate.py`.
- Current real output: `reports\ATLAS_T6_MANUAL_PARTICIPANT_REMAINING_IDENTITY_READBACK_GATE_20260526.md`, summary decision `atlas_social_manual_participant_event_identity_readback_gate_ready_report_only`, failed checks `[]`, input/readback/ready/blocked rows `4/4/4/0`, date/venue split `2/2`, unique selected event ids `11`, duplicate selector drift groups `0`, min participant evidence `1`, leak hits `0/0/0`, all write/promotion rows `0`.
- Self-correction: venue normalization now covers additional `OIL`, `ClubMe`, and `Coolwave` variants; report/source-kind wording is sanitized before strict leak/key scans.
- Boundary: report-only selected-serving readback over read-only `reports\atlas_serving_participant_delta_current_20260526_0016\atlas_serving.sqlite`; no source/raw DB open or write, serving SQLite write/rebuild, OCR execution, network/model call, graph fact acceptance, graph/vector/DB production write, public pointer, deploy/upload/review, memory, credential, destructive Git, 9router, or D: root action.
- Next resume pointer: `tools\stage7_rewrite\reports\atlas_social_manual_participant_remaining_identity_readback_gate_q6_20260526\event_identity_readback_ready_report_only.jsonl`.

## 2026-05-26 Atlas Q6/T5 Manual Participant Remaining Identity Recovery Gate

- `tools\stage7_rewrite\scripts\build_atlas_social_manual_participant_remaining_identity_recovery_gate.py` consumes the remaining event-date/source-year, same-date tiebreak, venue-alias lineage, multi-venue, and low-title work-order queues from the 11:18 blocked identity review packet.
- Regression coverage: `tools\stage7_rewrite\tests\test_build_atlas_social_manual_participant_remaining_identity_recovery_gate.py`.
- Current real output: `reports\ATLAS_T6_MANUAL_PARTICIPANT_REMAINING_IDENTITY_RECOVERY_GATE_20260526.md`, summary decision `atlas_social_manual_participant_remaining_identity_recovery_candidates_ready_report_only`, failed checks `[]`, input work orders `9`, readback candidate rows `4`, blocked rows `5`, same-date/venue candidates `2/2`, source-account batches `4`, unique selected event ids `11`, leak hits `0/0/0`, all write/promotion rows `0`.
- Boundary: report-only recovery over redacted JSONL; no SQLite open, source/raw DB open or write, serving SQLite write/rebuild, OCR execution, network/model call, graph fact acceptance, graph/vector/DB production write, public pointer, deploy/upload/review, memory, credential, destructive Git, 9router, or D: root action.

## 2026-05-26 Atlas Q6/T5 Manual Participant Overnight Midnight Acceptance Write Gate

- `tools\stage7_rewrite\scripts\build_atlas_social_manual_participant_overnight_midnight_acceptance_write_gate.py` consumes the 15:10 overnight-midnight readback-ready row and the target-DB provenance blocker summary, then emits a report-only manual midnight-boundary acceptance/write-gate contract under `tools\stage7_rewrite\reports\atlas_social_manual_participant_overnight_midnight_acceptance_write_gate_q6_20260526`.
- Regression coverage: `tools\stage7_rewrite\tests\test_build_atlas_social_manual_participant_overnight_midnight_acceptance_write_gate.py`.
- Current real output: `reports\ATLAS_T6_MANUAL_PARTICIPANT_OVERNIGHT_MIDNIGHT_ACCEPTANCE_WRITE_GATE_20260526.md`, summary decision `atlas_social_manual_participant_overnight_midnight_acceptance_write_gate_blocked_report_only`, failed checks `["source_raw_target_db_provenance_missing"]`, input/write/manual-ready rows `1/1/1`, source/raw target DB ready/blocked rows `0/1`, write execution allowed rows `0`, leak hits `0/0/0`, all write/promotion rows `0`.
- Boundary: report-only contract over redacted JSONL and summaries; no source/raw DB open or write, serving SQLite open/write/rebuild, OCR execution, network/model call, graph fact acceptance, graph/vector/DB production write, public pointer, deploy/upload/review, memory, credential, destructive Git, 9router, or D: root action.

## 2026-05-26 Atlas Q6/T5 Manual Participant Overnight Midnight Readback Gate

- `tools\stage7_rewrite\scripts\build_atlas_social_manual_participant_overnight_midnight_readback_gate.py` consumes the 14:42 midnight-boundary candidate, opens selected serving SQLite read-only, and emits a report-only readback gate under `tools\stage7_rewrite\reports\atlas_social_manual_participant_overnight_midnight_readback_gate_q6_20260526`.
- Regression coverage: `tools\stage7_rewrite\tests\test_build_atlas_social_manual_participant_overnight_midnight_readback_gate.py`.
- Current real output: `reports\ATLAS_T6_MANUAL_PARTICIPANT_OVERNIGHT_MIDNIGHT_READBACK_GATE_20260526.md`, summary decision `atlas_social_manual_participant_overnight_midnight_readback_gate_ready_report_only`, failed checks `[]`, input/readback/ready/blocked rows `1/1/1/0`, boundary segment readback rows `2`, unique selected event ids `5`, unique boundary dates `2`, boundary-start/midnight-date event rows `2/3`, min participant evidence `1`, leak hits `0/0/0`, all write/promotion rows `0`.
- Self-correction: the first real summary counted distinct boundary date values instead of event rows. The builder now records `date_counts`, with regression coverage for the `2/3` boundary-start/midnight event-row split.
- Boundary: report-only selected-serving readback over redacted JSONL and read-only `reports\atlas_serving_participant_delta_current_20260526_0016\atlas_serving.sqlite`; no source/raw DB open or write, serving SQLite write/rebuild, OCR execution, network/model call, graph fact acceptance, graph/vector/DB production write, public pointer, deploy, upload/review, memory, credential, destructive Git, 9router, or D: root action.
- Next resume pointer: `tools\stage7_rewrite\reports\atlas_social_manual_participant_overnight_midnight_readback_gate_q6_20260526\overnight_midnight_readback_ready_report_only.jsonl`.

## 2026-05-26 Atlas Q6/T5 Manual Participant Overnight Midnight Correction

- `tools\stage7_rewrite\scripts\build_atlas_social_manual_participant_overnight_midnight_correction.py` consumes the 14:38 overnight/span readback candidate plus the current-thread user correction `实际上应该是今天半夜`, then emits a report-only midnight-boundary correction packet under `tools\stage7_rewrite\reports\atlas_social_manual_participant_overnight_midnight_correction_q6_20260526`.
- Regression coverage: `tools\stage7_rewrite\tests\test_build_atlas_social_manual_participant_overnight_midnight_correction.py`.
- Current real output: `reports\ATLAS_T6_MANUAL_PARTICIPANT_OVERNIGHT_MIDNIGHT_CORRECTION_20260526.md`, summary decision `atlas_social_manual_participant_overnight_midnight_correction_ready_report_only`, failed checks `[]`, input rows `1`, midnight-boundary candidates `1`, blocked rows `0`, superseded prior split rows `1`, unique selected event ids `5`, leak hits `0/0/0`, all write/promotion rows `0`; now upstream evidence consumed by the 15:10 readback gate.
- Interpretation: OIL `Countdown to 2020` is normalized to `2019-12-31` crossing to `2020-01-01 00:00` Asia/Shanghai as a single overnight event boundary; the previous two-date split packet is upstream/superseded evidence.
- Boundary: report-only correction over redacted JSONL and user correction; no source/raw DB open or write, serving SQLite open/write/rebuild, OCR execution, network/model call, graph fact acceptance, graph/vector/DB production write, public pointer, deploy, upload/review, memory, credential, destructive Git, 9router, or D: root action.
- Upstream status: `tools\stage7_rewrite\reports\atlas_social_manual_participant_overnight_midnight_correction_q6_20260526\overnight_midnight_boundary_candidate_report_only.jsonl` was consumed by the 15:10 midnight-boundary readback gate.

## 2026-05-26 Atlas Q6/T5 Manual Participant Source Date Acceptance Write Gate

- `tools\stage7_rewrite\scripts\build_atlas_social_manual_participant_source_date_acceptance_write_gate.py` consumes the 13:10 source-date readback-ready rows, the readback summary, and the target-DB provenance blocker summary, then emits a report-only manual date-context acceptance/write-gate contract under `tools\stage7_rewrite\reports\atlas_social_manual_participant_source_date_acceptance_write_gate_q6_20260526`.
- Regression coverage: `tools\stage7_rewrite\tests\test_build_atlas_social_manual_participant_source_date_acceptance_write_gate.py`.
- Current real output: `reports\ATLAS_T6_MANUAL_PARTICIPANT_SOURCE_DATE_ACCEPTANCE_WRITE_GATE_20260526.md`, summary decision `atlas_social_manual_participant_source_date_acceptance_write_gate_blocked_report_only`, failed checks `["source_raw_target_db_provenance_missing"]`, input/write-gate/manual-ready rows `3/3/3`, source/raw target DB provenance ready rows `0`, source/raw target DB blocked rows `3`, source-account batches `2`, unique selected event ids/dates `6/3`, prewrite/rollback/postwrite required rows `3/3/3`, write execution allowed rows `0`, leak hits `0/0/0`, all write/promotion rows `0`.
- Self-correction: the builder now supports both legacy and current target-DB provenance count names after a first run misread legacy `target_db_provenance_blocked_rows` as absent.
- Boundary: report-only contract over redacted JSONL and summaries; no source/raw DB open or write, serving SQLite open/write/rebuild, OCR execution, network/model call, graph fact acceptance, graph/vector/DB production write, public pointer, deploy, upload/review, memory, credential, destructive Git, 9router, or D: root action.
- Next cursor: `tools\stage7_rewrite\reports\atlas_social_manual_participant_source_date_acceptance_write_gate_q6_20260526\source_raw_target_db_blocked_rows.jsonl`.

## 2026-05-26 Atlas Q6/T5 Manual Participant Source Date Readback Gate

- `tools\stage7_rewrite\scripts\build_atlas_social_manual_participant_source_date_readback_gate.py` consumes the 12:21 source-date-context candidate-ready rows, opens the selected serving SQLite read-only, and emits report-only readback/consolidation evidence under `tools\stage7_rewrite\reports\atlas_social_manual_participant_source_date_readback_gate_q6_20260526`.
- Regression coverage: `tools\stage7_rewrite\tests\test_build_atlas_social_manual_participant_source_date_readback_gate.py`.
- Current real output: `reports\ATLAS_T6_MANUAL_PARTICIPANT_SOURCE_DATE_READBACK_GATE_20260526.md`, summary decision `atlas_social_manual_participant_source_date_readback_gate_ready_report_only`, failed checks `[]`, input/readback/ready/blocked rows `3/3/3/0`, source-account batches `2`, unique selected event ids/dates `6/3`, duplicate selector drift groups `0`, min participant evidence count `1`, leak hits `0/0/0`, all write/promotion rows `0`; now direct upstream evidence consumed by the 14:07 source-date acceptance write-gate.
- Self-correction: strict leak grep initially flagged the upstream source-kind label `queue_token_account_title_exact`; output now uses scrubbed labels and the regression covers sensitive-key wording in report metadata.
- Boundary: report-only selected-serving readback over redacted JSONL; no source/raw DB open or write, serving SQLite write/rebuild, OCR execution, network/model call, graph fact acceptance, graph/vector/DB production write, public pointer, deploy, upload/review, memory, credential, destructive Git, 9router, or D: root action.
- Upstream status: `tools\stage7_rewrite\reports\atlas_social_manual_participant_source_date_readback_gate_q6_20260526\source_date_readback_ready_report_only.jsonl` was consumed by the 14:07 source-date acceptance write-gate.

## 2026-05-26 Atlas Q6/T5 Manual Participant Source Date Context Recovery

- `tools\stage7_rewrite\scripts\build_atlas_social_manual_participant_source_date_context_recovery.py` consumes the 11:18 source-date-context work orders and emits report-only recovery/readback evidence under `tools\stage7_rewrite\reports\atlas_social_manual_participant_source_date_context_recovery_q6_20260526`.
- Regression coverage: `tools\stage7_rewrite\tests\test_build_atlas_social_manual_participant_source_date_context_recovery.py`.
- Current real output: `reports\ATLAS_T6_MANUAL_PARTICIPANT_SOURCE_DATE_CONTEXT_RECOVERY_20260526.md`, summary decision `atlas_social_manual_participant_source_date_context_recovery_ready_report_only`, failed checks `[]`, input work orders `4`, review rows `4`, source-account batches `2`, candidate-ready rows `3`, source-artifact required rows `0`, overnight/span review rows `1`, ambiguous tiebreak rows `0`, leak hits `0/0/0`, all write/promotion rows `0`.
- Boundary: report-only local recovery over redacted JSONL; no source/raw DB open or write, serving SQLite open/write/rebuild, OCR execution, network/model call, graph fact acceptance, graph/vector/DB production write, public pointer, deploy, upload/review, memory, credential, destructive Git, 9router, or D: root action.
- Upstream status: `tools\stage7_rewrite\reports\atlas_social_manual_participant_source_date_context_recovery_q6_20260526\date_context_candidate_ready_report_only.jsonl` was consumed by the 13:10 source-date readback gate; the overnight/span review row remains closed for split/span review.

## 2026-05-26 Atlas Q6/T5 Manual Participant Blocked Identity Review

- `tools\stage7_rewrite\scripts\build_atlas_social_manual_participant_blocked_identity_review.py` consumes the 08:43 still-blocked manual event-identity rows and emits report-only recovery work orders under `tools\stage7_rewrite\reports\atlas_social_manual_participant_blocked_identity_review_q6_20260526`.
- Regression coverage: `tools\stage7_rewrite\tests\test_build_atlas_social_manual_participant_blocked_identity_review.py`.
- Current real output: `reports\ATLAS_T6_MANUAL_PARTICIPANT_BLOCKED_IDENTITY_REVIEW_20260526.md`, summary decision `atlas_social_manual_participant_blocked_identity_review_ready_report_only`, failed checks `[]`, input still-blocked rows `13`, review work-order rows `13`, source-account batches `4`, lane split source-date-context `4`, event-date/source-year `1`, same-date cluster tiebreak `2`, venue-alias lineage `4`, multi-venue split `1`, low-title manual review `1`, leak hits `0/0/0`, all write/promotion rows `0`.
- Boundary: report-only local recovery planning over redacted JSONL; no source/raw DB open or write, serving SQLite open/write/rebuild, OCR execution, network/model call, graph fact acceptance, graph/vector/DB production write, public pointer, deploy, upload/review, memory, credential, destructive Git, 9router, or D: root action.
- Next cursor: `tools\stage7_rewrite\reports\atlas_social_manual_participant_blocked_identity_review_q6_20260526\source_date_context_recovery_work_orders.jsonl`.

## 2026-05-26 Atlas Q6/T5 Manual Participant Visual API Response Smoke

- `tools\stage7_rewrite\scripts\build_atlas_social_manual_participant_visual_api_response_smoke.py` consumes the 10:40 visual API drilldown contract and samples, then emits report-only overview/detail/neighbor/search/cluster response fixtures under `tools\stage7_rewrite\reports\atlas_social_manual_participant_visual_api_response_smoke_q6_20260526`.
- Regression coverage: `tools\stage7_rewrite\tests\test_build_atlas_social_manual_participant_visual_api_response_smoke.py`.
- Current real output: `reports\ATLAS_T6_MANUAL_PARTICIPANT_VISUAL_API_RESPONSE_SMOKE_20260526.md`, summary decision `atlas_social_manual_participant_visual_api_response_smoke_ready_report_only`, failed checks `[]`, route contracts `5`, response fixtures overview/detail/neighbor/search/cluster `1/12/12/8/8`, detail-neighbor mismatch rows `0`, query-facet mismatch rows `0`, leak hits `0/0/0`, all write/promotion rows `0`.
- Boundary: report-only local visualization API response fixture smoke; no source/raw DB open or write, serving SQLite open/write/rebuild, OCR execution, network/model call, graph fact acceptance, graph/vector/DB production write, public pointer, deploy, upload/review, memory, credential, destructive Git, 9router, or D: root action.
- Next cursor: `tools\stage7_rewrite\reports\atlas_social_manual_participant_visual_api_response_smoke_q6_20260526\manual_participant_visual_api_response_manifest.json`.

## 2026-05-26 Atlas Q6/T5 Manual Participant Visual API Drilldown

- `tools\stage7_rewrite\scripts\build_atlas_social_manual_participant_visual_api_drilldown.py` consumes the 10:11 visual UI contract and emits report-only API route/detail/search/neighbor drilldown outputs under `tools\stage7_rewrite\reports\atlas_social_manual_participant_visual_api_drilldown_q6_20260526`.
- Regression coverage: `tools\stage7_rewrite\tests\test_build_atlas_social_manual_participant_visual_api_drilldown.py`.
- Current real output: `reports\ATLAS_T6_MANUAL_PARTICIPANT_VISUAL_API_DRILLDOWN_20260526.md`, summary decision `atlas_social_manual_participant_visual_api_drilldown_ready_report_only`, failed checks `[]`, input elements/nodes/edges `381/132/249`, DJ/event/venue nodes `70/51/11`, DJ-event/event-venue edges `198/51`, route/detail/neighbor/search samples `5/12/12/8`, cluster filters/samples `16/8`, zero-degree/dangling/duplicate/window-parse failures `0/0/0/0`, leak hits `0/0/0`, all write/promotion rows `0`.
- Boundary: report-only local visualization API drilldown; no source/raw DB open or write, serving SQLite open/write/rebuild, OCR execution, network/model call, graph fact acceptance, graph/vector/DB production write, public pointer, deploy, upload/review, memory, credential, destructive Git, 9router, or D: root action.
- Next cursor: `tools\stage7_rewrite\reports\atlas_social_manual_participant_visual_api_drilldown_q6_20260526\manual_participant_visual_api_contract.json`.

## 2026-05-26 Atlas Q6/T5 Manual Participant Visual UI/API Smoke

- `tools\stage7_rewrite\scripts\build_atlas_social_manual_participant_visual_smoke.py` consumes the 09:54 visual export graph, clusters, search drilldown, and graph-window rollup, then emits a report-only UI/API contract JSON, Cytoscape elements JSON, summary outputs, and top-level report under `tools\stage7_rewrite\reports\atlas_social_manual_participant_visual_smoke_q6_20260526`.
- Regression coverage: `tools\stage7_rewrite\tests\test_build_atlas_social_manual_participant_visual_smoke.py`.
- Current real output: `reports\ATLAS_T6_MANUAL_PARTICIPANT_VISUAL_SMOKE_20260526.md`, summary decision `atlas_social_manual_participant_visual_smoke_ready_report_only`, failed checks `[]`, input nodes/edges `132/249`, Cytoscape elements `381`, DJ/event/venue nodes `70/51/11`, DJ-event/event-venue edges `198/51`, cluster/search/window rows `16/121/70`, missing search/window/dangling/duplicates/not-ready `0/0/0/0/0`, leak hits `0/0/0`, all write/promotion rows `0`.
- Boundary: report-only local UI/API contract smoke; no source/raw DB open or write, serving SQLite open/write/rebuild, OCR execution, network/model call, graph fact acceptance, graph/vector/DB production write, public pointer, deploy, upload/review, memory, credential, destructive Git, 9router, or D: root action.

## 2026-05-26 Atlas Q6/T5 Manual Participant Visual Export

- `tools\stage7_rewrite\scripts\build_atlas_social_manual_participant_visual_export.py` consumes the graph/search consistency-ready rows, opens the selected serving SQLite read-only, emits local visualization graph JSON, cluster JSONL, search drilldown JSONL, graph-window rollup, and summary outputs under `tools\stage7_rewrite\reports\atlas_social_manual_participant_visual_export_q6_20260526`.
- Regression coverage: `tools\stage7_rewrite\tests\test_build_atlas_social_manual_participant_visual_export.py`.
- Current real output: `reports\ATLAS_T6_MANUAL_PARTICIPANT_VISUAL_EXPORT_20260526.md`, summary decision `atlas_social_manual_participant_visual_export_ready_report_only`, failed checks `[]`, input/cluster rows `16/16`, selected event ids `51`, visual event/DJ/venue nodes `51/70/11`, visual edges `249`, search drilldown rows `121`, graph-window rows `70`, parsed graph-window nodes/edges `4,380/5,554`, leak hits `0/0/0`, all write/promotion rows `0`.
- Boundary: report-only local visualization/search export; no source/raw DB open or write, serving SQLite write/rebuild, OCR execution, network/model call, graph fact acceptance, graph/vector/DB production write, public pointer, deploy, upload/review, memory, credential, destructive Git, 9router, or D: root action.

## 2026-05-26 Atlas Q6/T5 Manual Participant Graph/Search Consistency

- `tools\stage7_rewrite\scripts\build_atlas_social_manual_participant_graph_search_consistency.py` consumes the Q6 event-identity readback ready rows, opens the selected serving SQLite read-only, streams the local full relation bundle, validates event/DJ/search/graph-window/bundle coverage, and emits outputs under `tools\stage7_rewrite\reports\atlas_social_manual_participant_graph_search_consistency_q6_20260526`.
- Regression coverage: `tools\stage7_rewrite\tests\test_build_atlas_social_manual_participant_graph_search_consistency.py`.
- Current real output: `reports\ATLAS_T6_MANUAL_PARTICIPANT_GRAPH_SEARCH_CONSISTENCY_20260526.md`, summary decision `atlas_social_manual_participant_graph_search_consistency_ready_report_only`, failed checks `[]`, input/consistency/ready/blocked rows `16/16/16/0`, unique selected event ids `51`, serving DJ-event edges `198`, unique DJ ids `70`, search event/DJ docs `51/70`, graph-window DJ seeds `70`, bundle coverage `51/70/198/51`, leak hits `0/0/0`, all write/promotion rows `0`.
- Boundary: report-only local graph/search consistency; no source/raw DB open or write, serving SQLite write/rebuild, OCR execution, network/model call, graph fact acceptance, graph/vector/DB production write, public pointer, deploy, upload/review, memory, credential, destructive Git, 9router, or D: root action.

## 2026-05-26 Atlas Q6 Manual Participant Event Identity Readback Gate

- `tools\stage7_rewrite\scripts\build_atlas_social_manual_participant_event_identity_readback_gate.py` consumes the Q6 event-identity resolution `manual_event_identity_resolution_candidates_deduped.jsonl`, opens the selected serving SQLite read-only, validates selectors/source/event/participant evidence, and emits outputs under `tools\stage7_rewrite\reports\atlas_social_manual_participant_event_identity_readback_gate_q6_20260526`.
- Regression coverage: `tools\stage7_rewrite\tests\test_build_atlas_social_manual_participant_event_identity_readback_gate.py`.
- Current real output: `reports\ATLAS_T6_MANUAL_PARTICIPANT_EVENT_IDENTITY_READBACK_GATE_20260526.md`, summary decision `atlas_social_manual_participant_event_identity_readback_gate_ready_report_only`, failed checks `[]`, input/readback/ready/blocked rows `16/16/16/0`, date-resolved ready rows `10`, venue-alias ready rows `6`, unique selected event ids `51`, duplicate selector drift groups `0`, min participant evidence count `1`, leak hits `0/0/0`, all write/promotion rows `0`.
- Self-correction: first real run over-blocked `5` rows on venue aliases; `OIL CLUB`, `OIL Mainroom`, and `Dada Kunming & 桠雀` now normalize correctly with focused regression coverage.
- Boundary: report-only selected-serving readback; no source/raw DB open or write, serving SQLite write/rebuild, OCR execution, network/model call, graph fact acceptance, graph/vector/DB production write, public pointer, deploy, upload/review, memory, credential, destructive Git, 9router, or D: root action.

## 2026-05-26 Atlas Q6 Manual Participant Event Identity Resolution Packet

- `tools\stage7_rewrite\scripts\build_atlas_social_manual_participant_event_identity_resolution_packet.py` consumes the Q6 blocker-recovery `manual_event_identity_review_work_orders.jsonl`, derives report-only date/venue-alias resolution candidates, dedupes selector hashes, and emits outputs under `tools\stage7_rewrite\reports\atlas_social_manual_participant_event_identity_resolution_q6_20260526`.
- Regression coverage: `tools\stage7_rewrite\tests\test_build_atlas_social_manual_participant_event_identity_resolution_packet.py`.
- Current real output: `reports\ATLAS_T6_MANUAL_PARTICIPANT_EVENT_IDENTITY_RESOLUTION_PACKET_20260526.md`, summary decision `atlas_social_manual_participant_event_identity_resolution_candidates_ready_report_only`, failed checks `[]`, input rows `31`, resolution candidates `18`, deduped candidates `16`, date-resolved candidates `12`, venue-alias-resolved candidates `6`, still blocked rows `13`, duplicate selector groups `2`, leak hits `0/0/0`, all write/promotion rows `0`.
- Self-correction: regression caught a multi-venue alias bug; `THE BOX ... DADA BEIJING` is now blocked as multi-venue before `Dada Beijing` alias normalization can fire.
- Boundary: report-only local review; no SQLite open, OCR execution, network/model call, graph fact acceptance, source/raw Atlas DB write, serving SQLite write/rebuild, graph/vector/DB production write, public pointer, deploy, upload/review, memory, credential, destructive Git, 9router, or D: root action.

## 2026-05-26 Atlas Q6 Manual Participant Source/OCR Localization Probe

- `tools\stage7_rewrite\scripts\probe_atlas_social_manual_participant_source_ocr_localization.py` consumes the Q6 blocker-recovery `source_ocr_recovery_work_orders.jsonl`, then reuses the existing local source/OCR localization helper to emit a Q6-specific report-only probe under `tools\stage7_rewrite\reports\atlas_social_manual_participant_source_ocr_localization_q6_20260526`.
- Regression coverage: `tools\stage7_rewrite\tests\test_probe_atlas_social_manual_participant_source_ocr_localization.py`.
- Current real output: `reports\ATLAS_T6_MANUAL_PARTICIPANT_SOURCE_OCR_LOCALIZATION_PROBE_20260526.md`, summary decision `atlas_social_manual_participant_source_ocr_localization_blocked_report_only`, failed checks `[]`, work-order rows `1`, source DB article rows found `1`, source URL sidecar rows found `1`, existing OCR/Markdown candidate rows `0`, exact-date candidate rows `1`, acceptance-ready rows `0`, still blocked rows `1`, leak hits `0/0/0`.
- Boundary: report-only local probe; no OCR execution, network fetch, model call, graph fact acceptance, source/raw Atlas DB write, serving SQLite write/rebuild, graph/vector/DB production write, public pointer, deploy, upload/review, memory, credential, destructive Git, 9router, or D: root action.

## 2026-05-26 Atlas Q6 Manual Participant Blocker Recovery Packet

- `tools\stage7_rewrite\scripts\build_atlas_social_manual_participant_blocker_recovery_packet.py` consumes the Q6 source-context blocked rows, source/OCR recovery row, acceptance blocked rows, and manual event-identity blocked rows, then emits report-only recovery work orders under `tools\stage7_rewrite\reports\atlas_social_manual_participant_blocker_recovery_q6_20260526`.
- Regression coverage: `tools\stage7_rewrite\tests\test_build_atlas_social_manual_participant_blocker_recovery_packet.py`.
- Current real output: `reports\ATLAS_T6_MANUAL_PARTICIPANT_BLOCKER_RECOVERY_PACKET_20260526.md`, summary decision `atlas_social_manual_participant_blocker_recovery_ready_report_only`, failed checks `[]`, inputs `5/1/2/31`, recovery work orders `38`, lane split source/OCR `1`, manual event-match `4`, event-evidence repair `2`, manual event-identity `31`, source-account batches `4`, leak hits `0/0/0`, all write/promotion rows `0`.
- Boundary: report-only recovery work orders; no SQLite open, graph fact acceptance, source/raw Atlas DB open/mutation, serving SQLite write/rebuild, graph/vector/DB production write, public pointer, deploy, upload/review, memory, credential, network/model/paid API, destructive Git, 9router, or D: root action.

## 2026-05-26 Atlas Q6 Manual Participant Target DB Provenance Packet

- `tools\stage7_rewrite\scripts\build_atlas_social_manual_participant_target_db_provenance_packet.py` consumes the Q6 real snapshot blocked rows, prewrite rows, and bounded SSOT/upstream artifacts, then emits a report-only target DB provenance blocker under `tools\stage7_rewrite\reports\atlas_social_manual_participant_target_db_provenance_q6_20260526`.
- Regression coverage: `tools\stage7_rewrite\tests\test_build_atlas_social_manual_participant_target_db_provenance_packet.py`.
- Current real output: `reports\ATLAS_T6_MANUAL_PARTICIPANT_TARGET_DB_PROVENANCE_20260526.md`, summary decision `atlas_social_manual_participant_target_db_provenance_blocked_report_only`, failed checks `["target_db_provenance_blocked"]`, input blocked/prewrite rows `46/46`, candidate refs `35`, unique paths `35`, direct existing explicit source/raw target DB paths `0`, serving read-model rejected paths `20`, source DB references not bound to Q6 gate `3`, ready/blocked rows `0/46`, leak hits `0/0/0`, all write/promotion rows `0`, target/source DB opened `false`.
- Boundary: report-only blocker because no explicit source/raw target DB is bound to the Q6 gate; no SQLite open, graph fact acceptance, source/raw Atlas DB open/mutation, serving SQLite write/rebuild, graph/vector/DB production write, public pointer, deploy, upload/review, memory, credential, network/model/paid API, destructive Git, 9router, or D: root action.

## 2026-05-26 Atlas Q6 Manual Participant DB Real Snapshot Gate

- `tools\stage7_rewrite\scripts\build_atlas_social_manual_participant_db_real_snapshot_gate.py` consumes the Q6 manual participant DB prewrite snapshot rows and summary, then emits a report-only real snapshot gate under `tools\stage7_rewrite\reports\atlas_social_manual_participant_db_real_snapshot_gate_q6_20260526`.
- Regression coverage: `tools\stage7_rewrite\tests\test_build_atlas_social_manual_participant_db_real_snapshot_gate.py`.
- Current real output: `reports\ATLAS_T6_MANUAL_PARTICIPANT_DB_REAL_SNAPSHOT_GATE_20260526.md`, summary decision `atlas_social_manual_participant_db_real_snapshot_gate_blocked_report_only`, failed checks `["blocked_rows_present"]`, input prewrite snapshot rows `46`, candidate rows after contract checks `46`, real snapshot rows `0`, blocked rows `46`, explicit target DB present/opened read-only `0/0`, real snapshot hashes `0`, duplicate hashes `0`, leak hits `0/0/0`, all write/promotion rows `0`, target DB opened read-only `false`.
- Boundary: report-only blocker because no explicit source/raw target DB is named; no graph fact acceptance, source/raw Atlas DB open/mutation, serving SQLite write/rebuild, graph/vector/DB production write, public pointer, deploy, upload/review, memory, credential, network/model/paid API, destructive Git, 9router, or D: root action.

## 2026-05-26 Atlas Q6 Manual Participant DB Prewrite Snapshot Packet

- `tools\stage7_rewrite\scripts\build_atlas_social_manual_participant_db_prewrite_snapshot_packet.py` consumes the Q6 manual participant DB write-gate target rows and summary, then emits a report-only prewrite snapshot packet under `tools\stage7_rewrite\reports\atlas_social_manual_participant_db_prewrite_snapshot_q6_20260526`.
- Regression coverage: `tools\stage7_rewrite\tests\test_build_atlas_social_manual_participant_db_prewrite_snapshot_packet.py`.
- Current real output: `reports\ATLAS_T6_MANUAL_PARTICIPANT_DB_PREWRITE_SNAPSHOT_PACKET_20260526.md`, summary decision `atlas_social_manual_participant_db_prewrite_snapshot_ready_report_only`, failed checks `[]`, input target rows `46`, prewrite snapshot rows `46`, blocked rows `0`, event-id/semantic split `27/19`, unique event_ids `199`, planned identity-lineage edges report-only `161`, participant evidence total `730`, contract row hashes `46`, duplicate hashes `0`, leak hits `0/0/0`, all write/promotion rows `0`, source DB opened/written `false/false`.
- Boundary: report-only prewrite snapshot; no graph fact acceptance, source/raw Atlas DB open/mutation, serving SQLite write/rebuild, graph/vector/DB production write, public pointer, deploy, upload/review, memory, credential, network/model/paid API, destructive Git, 9router, or D: root action.

## 2026-05-26 Atlas Q6 Manual Participant DB Write-Gate Contract

- `tools\stage7_rewrite\scripts\build_atlas_social_manual_participant_db_write_gate_packet.py` consumes the Q6 manual participant readback preflight ready rows, readback summary, and duplicate selector evidence, then emits a report-only explicit DB write-gate contract under `tools\stage7_rewrite\reports\atlas_social_manual_participant_db_write_gate_q6_20260526`.
- Regression coverage: `tools\stage7_rewrite\tests\test_build_atlas_social_manual_participant_db_write_gate_packet.py`.
- Current real output: `reports\ATLAS_T6_MANUAL_PARTICIPANT_DB_WRITE_GATE_20260526.md`, summary decision `atlas_social_manual_participant_db_write_gate_ready_report_only`, failed checks `[]`, input ready rows `46`, write-gate target rows `46`, blocked rows `0`, event-id/semantic split `27/19`, unique event_ids `199`, planned identity-lineage edges report-only `161`, participant evidence total `730`, duplicate selector evidence input/matched/blocked `5/5/0`, prewrite snapshot/rollback/postwrite readback required rows `46/46/46`, leak hits `0/0/0`, all write/promotion rows `0`.
- Boundary: report-only write-gate contract; no graph fact acceptance, source/raw Atlas DB mutation, serving SQLite write/rebuild, graph/vector/DB production write, public pointer, deploy, upload/review, memory, credential, network/model/paid API, destructive Git, 9router, or D: root action.

## 2026-05-26 Atlas Q6 Manual Participant Readback Preflight

- `tools\stage7_rewrite\scripts\build_atlas_social_manual_participant_readback_preflight_packet.py` consumes the Q6 manual participant consolidation gate readback cursors and selected serving SQLite in read-only mode, then emits a report-only DB readback/write-preflight packet under `tools\stage7_rewrite\reports\atlas_social_manual_participant_readback_preflight_q6_20260526`.
- Regression coverage: `tools\stage7_rewrite\tests\test_build_atlas_social_manual_participant_readback_preflight_packet.py`.
- Current real output: `reports\ATLAS_T6_MANUAL_PARTICIPANT_READBACK_PREFLIGHT_20260526.md`, summary decision `atlas_social_manual_participant_readback_preflight_ready_report_only`, failed checks `[]`, input event-id/semantic rows `27/19`, readback preflight rows `46`, write-preflight ready report-only rows `46`, blocked rows `0`, unique candidate event_ids `199`, duplicate selector evidence rows `5`, min participant evidence count per event `1`, leak hits `0/0/0`, all write/promotion rows `0`.
- Boundary: report-only readback/write-preflight over selected serving SQLite read-only; no graph fact acceptance, source/raw Atlas DB mutation, serving SQLite write/rebuild, graph/vector/DB production write, public pointer, deploy, upload/review, memory, credential, network/model/paid API, destructive Git, 9router, or D: root action.

## 2026-05-26 Atlas Q6 Manual Participant Consolidation Gate Packet

- `tools\stage7_rewrite\scripts\build_atlas_social_manual_participant_consolidation_gate_packet.py` consumes the Q6 event-id and semantic cluster consolidation candidates, then emits a report-only manual DB readback gate packet under `tools\stage7_rewrite\reports\atlas_social_manual_participant_consolidation_gate_q6_20260526`.
- Regression coverage: `tools\stage7_rewrite\tests\test_build_atlas_social_manual_participant_consolidation_gate_packet.py`.
- Current real output: `reports\ATLAS_T6_MANUAL_PARTICIPANT_CONSOLIDATION_GATE_PACKET_20260526.md`, summary decision `atlas_social_manual_participant_consolidation_gate_packet_ready_report_only`, failed checks `[]`, event-id candidates `29`, semantic cluster candidates `22`, consolidation gate targets `51`, ready before selector dedupe `51`, deduped manual DB readback rows `46`, event-id/semantic split `27/19`, duplicate selector groups/collapsed rows `5/5`, blocked rows `0`, leak hits `0/0/0`, all write/promotion rows `0`.
- Boundary: report-only gate packet; no source/raw Atlas DB mutation, serving SQLite read/write/rebuild, graph/vector/DB production write, public pointer, deploy, upload/review, memory, credential, network/model/paid API, destructive Git, 9router, or D: root action.

## 2026-05-26 Atlas Q6 Manual Participant Event Cluster Review

- `tools\stage7_rewrite\scripts\build_atlas_social_manual_participant_event_cluster_review.py` consumes `tools\stage7_rewrite\reports\atlas_social_manual_participant_acceptance_precheck_q6_20260526\event_id_dedupe_review_rows.jsonl` and `ambiguous_event_cluster_review_rows.jsonl`, then emits a report-only event identity normalization packet under `tools\stage7_rewrite\reports\atlas_social_manual_participant_event_cluster_review_q6_20260526`.
- Regression coverage: `tools\stage7_rewrite\tests\test_build_atlas_social_manual_participant_event_cluster_review.py`.
- Current real output: `reports\ATLAS_T6_MANUAL_PARTICIPANT_EVENT_CLUSTER_REVIEW_20260526.md`, summary decision `atlas_social_manual_participant_event_cluster_review_candidates_ready_report_only`, failed checks `[]`, input rows `29/53`, event-id consolidation candidates `29`, semantic cluster consolidation candidates `22`, manual event identity blocked rows `31`, leak hits `0/0/0`, all write/promotion rows `0`.
- Boundary: report-only event identity normalization over existing redacted JSONL; no source/raw Atlas DB mutation, serving SQLite read/write/rebuild, graph/vector/DB production write, public pointer, deploy, upload/review, memory, credential, network/model/paid API, destructive Git, 9router, or D: root action.

## 2026-05-26 Atlas Q6 Manual Participant Acceptance Precheck

- `tools\stage7_rewrite\scripts\build_atlas_social_manual_participant_acceptance_precheck.py` consumes `tools\stage7_rewrite\reports\atlas_social_manual_participant_source_context_review_q6_20260526\deterministic_acceptance_precheck_candidates.jsonl` and emits a report-only deterministic precheck packet under `tools\stage7_rewrite\reports\atlas_social_manual_participant_acceptance_precheck_q6_20260526`.
- Regression coverage: `tools\stage7_rewrite\tests\test_build_atlas_social_manual_participant_acceptance_precheck.py`.
- Current real output: `reports\ATLAS_T6_MANUAL_PARTICIPANT_ACCEPTANCE_PRECHECK_20260526.md`, summary decision `atlas_social_manual_participant_acceptance_precheck_review_ready_report_only`, failed checks `[]`, input candidate rows `89`, strict manual acceptance review-ready rows `5`, semantic duplicate event-id dedupe rows `29`, ambiguous event-cluster review rows `53`, blocked event-evidence rows `2`, leak hits `0/0/0`, all write/promotion rows `0`.
- Boundary: report-only deterministic precheck over existing JSONL; no source/raw Atlas DB mutation, serving SQLite read/write/rebuild, graph/vector/DB production write, public pointer, deploy, upload/review, memory, credential, network/model/paid API, destructive Git, 9router, or D: root action.

## 2026-05-26 Atlas Q6 Manual Participant Source-Context Review

- `tools\stage7_rewrite\scripts\build_atlas_social_manual_participant_source_context_review.py` consumes `tools\stage7_rewrite\reports\atlas_social_manual_participant_review_triage_q6_20260526\manual_participant_review_work_orders.jsonl` plus `source_account_batch_queue.jsonl`, opens the selected serving SQLite `reports\atlas_serving_participant_delta_current_20260526_0016\atlas_serving.sqlite` read-only, and emits report-only source-context/manual-evidence review rows under `tools\stage7_rewrite\reports\atlas_social_manual_participant_source_context_review_q6_20260526`.
- Regression coverage: `tools\stage7_rewrite\tests\test_build_atlas_social_manual_participant_source_context_review.py`.
- Current real output: `reports\ATLAS_T6_MANUAL_PARTICIPANT_SOURCE_CONTEXT_REVIEW_20260526.md`, summary decision `atlas_social_manual_participant_source_context_review_candidates_ready_report_only`, failed checks `[]`, selected source accounts `Dada Kunming`, `Dada Bar Beijing`, `OIL油`, `TRUST 相信电音`, input/reviewed rows `114/94`, matched source-ref rows `93`, matched event-candidate rows `89`, deterministic acceptance precheck candidate rows `89`, source-context blocked rows `5`, source/OCR recovery required rows `1`, leak hits `0/0/0`.
- Boundary: report-only local review with selected serving SQLite read-only; no source/raw Atlas DB mutation, serving SQLite rebuild/write, graph/vector/DB production write, public pointer, deploy, upload/review, memory, credential, network/model/paid API, destructive Git, 9router, or D: root action.

## 2026-05-26 Atlas Q6 Manual Participant Review Triage

- `tools\stage7_rewrite\scripts\build_atlas_social_manual_participant_review_triage.py` consumes `tools\stage7_rewrite\reports\atlas_social_broader_recovery_acceptance_gate_q6_20260526\manual_participant_review_candidates.jsonl` and emits report-only participant review work orders plus source-account batch queues under `tools\stage7_rewrite\reports\atlas_social_manual_participant_review_triage_q6_20260526`.
- Regression coverage: `tools\stage7_rewrite\tests\test_build_atlas_social_manual_participant_review_triage.py`.
- Current real output: `reports\ATLAS_T6_MANUAL_PARTICIPANT_REVIEW_TRIAGE_20260526.md`, summary decision `atlas_social_manual_participant_review_triage_ready_report_only`, failed checks `[]`, input/work-order rows `114/114`, high-yield source-context review rows `105`, standard source-context review rows `9`, source-account batches `13`, leak hits `0/0/0`.
- Boundary: report-only local triage; no source/raw Atlas DB mutation, serving SQLite rebuild/write, graph/vector/DB production write, public pointer, deploy, upload/review, memory, credential, network/model/paid API, destructive Git, 9router, or D: root action.

## 2026-05-26 Atlas T5 Source Acquisition Bounded Fetch

- `tools\stage7_rewrite\scripts\run_atlas_source_acquisition_bounded_fetch.py` consumes `tools\stage7_rewrite\reports\atlas_source_acquisition_preflight_t5_20260526\fetch_preflight_ready_work_orders.jsonl` and the source-url sidecar read-only, verifies URL SHA256 before fetch, stores fetched responses only under report-local hashed bundles, and emits redacted manifest/status rows under `tools\stage7_rewrite\reports\atlas_source_acquisition_bounded_fetch_t5_20260526`.
- Regression coverage: `tools\stage7_rewrite\tests\test_run_atlas_source_acquisition_bounded_fetch.py`.
- Current real output: `reports\ATLAS_T5_SOURCE_ACQUISITION_BOUNDED_FETCH_20260526.md`, summary decision `atlas_source_acquisition_bounded_fetch_blocked_report_only`, failed checks `[]`, input work orders `5`, source URL hash verified rows `5`, network fetch executed rows `5`, response artifact written rows `5`, article artifact ready rows `0`, blocked/not-ready rows `5`, OCR generation allowed now `0`, acceptance precheck allowed now `0`, leak hits `0/0/0`.
- Self-correction: the runner now distinguishes response artifacts from article-ready artifacts. Verification-shell HTML with status `200` is blocked when `js_content_text_len=0`, title-prefix evidence is absent, article marker is absent, and weak/block markers are present.
- Boundary: bounded public fetch and report-local response artifacts only; no OCR/LLM/model execution, source/OCR acceptance, graph fact acceptance, source/raw DB mutation, serving SQLite write/rebuild, public pointer, deploy, upload/review, memory, credential/browser-profile read, model/paid API, destructive Git, 9router, or D: root action.

## 2026-05-26 Atlas T5 Source Acquisition Preflight Work Orders

- `tools\stage7_rewrite\scripts\build_atlas_source_acquisition_preflight_work_order.py` consumes `tools\stage7_rewrite\reports\atlas_source_artifact_acquisition_plan_t5_20260526\external_source_acquisition_candidates.jsonl` and the source-url sidecar read-only, verifies URL SHA256 alignment without emitting raw URLs, and emits report-only work orders under `tools\stage7_rewrite\reports\atlas_source_acquisition_preflight_t5_20260526`.
- Regression coverage: `tools\stage7_rewrite\tests\test_build_atlas_source_acquisition_preflight_work_order.py`.
- Current real output: `reports\ATLAS_T5_SOURCE_ACQUISITION_PREFLIGHT_20260526.md`, summary decision `atlas_source_acquisition_preflight_ready_report_only`, failed checks `[]`, input rows `5`, sidecar source URL found rows `5`, source URL hash match rows `5`, fetch preflight-ready rows `5`, blocked rows `0`, OCR generation allowed now `0`, acceptance precheck allowed now `0`, leak hits `0/0/0`.
- Boundary: report-only preflight/work-order generation; no source URL fetch, OCR/LLM/model execution, graph fact acceptance, source/raw DB mutation, serving SQLite write/rebuild, public pointer, deploy, upload/review, memory, credential, network/model/paid API, destructive Git, 9router, or D: root action.

## 2026-05-26 Atlas T5 Source Artifact Acquisition Plan

- `tools\stage7_rewrite\scripts\build_atlas_source_artifact_acquisition_plan.py` consumes `tools\stage7_rewrite\reports\atlas_source_ocr_artifact_recovery_execution_gate_t5_20260526\source_artifact_acquisition_queue.jsonl`, bounded source-url JSONL, and the bounded host artifact root, then emits a report-only acquisition plan under `tools\stage7_rewrite\reports\atlas_source_artifact_acquisition_plan_t5_20260526`.
- Regression coverage: `tools\stage7_rewrite\tests\test_build_atlas_source_artifact_acquisition_plan.py`.
- Current real output: `reports\ATLAS_T5_SOURCE_ARTIFACT_ACQUISITION_PLAN_20260526.md`, summary decision `atlas_source_artifact_acquisition_plan_external_acquisition_required_report_only`, failed checks `[]`, target rows `5`, source URL present rows `5`, local image count total `100`, local artifact-ready rows `0`, external acquisition candidates `5`, OCR generation allowed rows `0`, leak hits `0/0/0`.
- Boundary: report-only acquisition planning; no source URL fetch, OCR/LLM/model execution, graph fact acceptance, source/raw DB mutation, serving SQLite write/rebuild, public pointer, deploy, upload/review, memory, credential, network/model/paid API, destructive Git, 9router, or D: root action.

## 2026-05-26 Atlas T5 Source/OCR Exact-Date Review Packet

- `tools\stage7_rewrite\scripts\build_atlas_source_ocr_exact_date_review_packet.py` consumes the execution-gate `exact_date_review_queue.jsonl`, reads local Atlas SQLite `articles` and `entities` evidence read-only, and emits a dedicated report-only exact-date packet under `tools\stage7_rewrite\reports\atlas_source_ocr_exact_date_review_t5_20260526`.
- Regression coverage: `tools\stage7_rewrite\tests\test_build_atlas_source_ocr_exact_date_review_packet.py`.
- Current real output: `reports\ATLAS_T5_SOURCE_OCR_EXACT_DATE_REVIEW_20260526.md`, summary decision `atlas_source_ocr_exact_date_review_blocked_report_only`, failed checks `[]`, input rows `2`, article rows found `2`, entity evidence rows scanned `29`, image OCR rows scanned `4`, full exact-date candidates `0`, still blocked rows `2`, leak hits `0/0/0`.
- Boundary: report-only exact-date review; no OCR/LLM/model execution, graph fact acceptance, source/raw DB mutation, serving SQLite write/rebuild, public pointer, deploy, upload/review, memory, credential, network/model/paid API, destructive Git, 9router, or D: root action.

## 2026-05-26 Atlas Q6 Broader Recovery Acceptance Gate

- `tools\stage7_rewrite\scripts\build_atlas_social_broader_recovery_acceptance_gate.py` consumes `tools\stage7_rewrite\reports\atlas_social_broader_source_context_recovery_q6_20260526\combined_broader_recovery_review_slice.jsonl` and emits a report-only acceptance gate under `tools\stage7_rewrite\reports\atlas_social_broader_recovery_acceptance_gate_q6_20260526`.
- Regression coverage: `tools\stage7_rewrite\tests\test_build_atlas_social_broader_recovery_acceptance_gate.py`.
- Current real output: `reports\ATLAS_T6_BROADER_RECOVERY_ACCEPTANCE_GATE_20260526.md`, summary decision `atlas_social_broader_recovery_acceptance_blocked_report_only`, failed checks `[]`, input rows `320`, deterministic acceptance-ready rows `0`, manual participant review candidates `114`, blocked rows `320`, leak hits `0/0/0`.
- Boundary: report-only gate; no source/raw DB mutation, serving SQLite rebuild/write, graph/vector/DB production write, public pointer, deploy, upload/review, memory, credential, network/model/paid API, destructive Git, 9router, or D: root action.

## 2026-05-26 Atlas T5 Source/OCR Exact-Date Review - Superseded Implementation Note

- The earlier 04:20 reuse of `build_atlas_source_ocr_fast_date_repair_attempt.py` is superseded by the dedicated 04:31 exact-date review packet above, because the dedicated packet scans existing entity/image-OCR evidence and has direct regression coverage.

## 2026-05-26 Atlas T5 Source/OCR Artifact Recovery Execution Gate

- `tools\stage7_rewrite\scripts\build_atlas_source_ocr_artifact_recovery_execution_gate.py` consumes the 03:48 localization queues, bounded source-url JSONL, and bounded host artifact root metadata, then emits a report-only execution gate under `tools\stage7_rewrite\reports\atlas_source_ocr_artifact_recovery_execution_gate_t5_20260526`.
- Regression coverage: `tools\stage7_rewrite\tests\test_build_atlas_source_ocr_artifact_recovery_execution_gate.py`.
- Current real output: `reports\ATLAS_T5_SOURCE_OCR_ARTIFACT_RECOVERY_EXECUTION_GATE_20260526.md`, summary decision `atlas_source_ocr_artifact_recovery_execution_gate_blocked_report_only`, failed checks `[]`, target rows `7`, exact-date review rows `2`, OCR/Markdown missing rows `5`, local OCR/Markdown generation-ready rows `0`, source artifact acquisition required rows `5`, acceptance-precheck allowed rows `0`, host source-dir-present rows `0`, source-url post-date/time rows `0/0`, leak hits `0/0/0`.
- LLM critique/self-correction: the gate prevents a blind OCR retry when image counts exist but no matching local source artifact directory is present; it also keeps source URLs and local paths hashed/redacted and rejects D: input roots.
- Boundary: report-only execution gate; no OCR/LLM/model execution, graph fact acceptance, source/raw DB mutation, serving SQLite write/rebuild, public pointer, deploy, upload/review, memory, credential, network/model/paid API, destructive Git, 9router, or D: root action.

## 2026-05-26 Atlas T5 Source/OCR Artifact Localization Probe

- `tools\stage7_rewrite\scripts\probe_atlas_source_ocr_artifact_localization.py` consumes `tools\stage7_rewrite\reports\atlas_source_ocr_artifact_recovery_packet_t5_20260526\source_ocr_artifact_recovery_work_orders.jsonl`, first-batch evidence rows, Atlas local candidate DB, source-url sidecar DB, and a bounded host-html artifact root inspection, then emits report-only localization rows and next queues under `tools\stage7_rewrite\reports\atlas_source_ocr_artifact_localization_probe_t5_20260526`.
- Regression coverage: `tools\stage7_rewrite\tests\test_probe_atlas_source_ocr_artifact_localization.py`.
- Current real output: `reports\ATLAS_T5_SOURCE_OCR_ARTIFACT_LOCALIZATION_PROBE_20260526.md`, summary decision `atlas_source_ocr_artifact_localization_probe_blocked_report_only`, failed checks `[]`, target rows `7`, fast-date rows `2`, event OCR/date rows `5`, existing OCR/Markdown candidate rows `2`, missing OCR/Markdown rows `5`, exact date candidate rows `0`, acceptance-ready rows `0`, still blocked rows `7`, leak hits `0/0/0`.
- LLM critique/self-correction: the probe prevents a stale acceptance loop by splitting the next cursor into `ocr_candidate_present_date_blocked.jsonl` and `ocr_markdown_missing_generation_queue.jsonl`; tests cover URL redaction, D-drive rejection, and date false-positive rejection.
- Boundary: report-only localization probe; no OCR/LLM/model execution, graph fact acceptance, source/raw DB mutation, serving SQLite write/rebuild, public pointer, deploy, upload/review, memory, credential, network/model/paid API, destructive Git, 9router, or D: root action.

## 2026-05-26 Atlas T5 Source/OCR Artifact Recovery Packet

- `tools\stage7_rewrite\scripts\build_atlas_source_ocr_artifact_recovery_packet.py` consumes `tools\stage7_rewrite\reports\atlas_source_ocr_fast_date_repair_attempt_t5_20260526\date_blocked_rows.jsonl`, `tools\stage7_rewrite\reports\atlas_source_ocr_first_batch_repair_targets_t5_20260526\event_like_repair_targets.jsonl`, and `tools\stage7_rewrite\reports\atlas_source_ocr_first_batch_repair_targets_t5_20260526\ocr_markdown_repair_targets.jsonl`, then emits explicit report-only recovery queues under `tools\stage7_rewrite\reports\atlas_source_ocr_artifact_recovery_packet_t5_20260526`.
- Regression coverage: `tools\stage7_rewrite\tests\test_build_atlas_source_ocr_artifact_recovery_packet.py`.
- Current real output: `reports\ATLAS_T5_SOURCE_OCR_ARTIFACT_RECOVERY_PACKET_20260526.md`, summary decision `atlas_source_ocr_artifact_recovery_packet_ready_report_only`, failed checks `[]`, input rows `2/7/18`, unique work orders `20`, fast-date artifact recovery rows `2`, event OCR+date repair rows `5`, OCR/Markdown localization rows `13`, acceptance hold rows `20`, ready for acceptance now `0`, source-account rollup rows `9`, leak hits `0/0/0`.
- LLM audit/self-correction: the first real run caught sensitive-key wording (`token`) in upstream evidence labels; the builder now scrubs sensitive-key words before leak scan and the regression asserts no raw URL/token leak.
- Boundary: report-only artifact recovery packet; no OCR/LLM/model execution, graph fact acceptance, source/raw DB mutation, serving SQLite write/rebuild, public pointer, deploy, upload/review, memory, credential, network/model/paid API, destructive Git, 9router, or D: root action.

## 2026-05-26 Atlas Production Graph Touch-Full Write

- `tools\stage7_rewrite\scripts\promote_graph_to_production.py` was executed in live `promote` mode for staging run `stage7_all_full_llm_138102_20260520` and promotion run `stage7_all_full_llm_138102_prod_20260520`.
- Current real output: `reports\ATLAS_PRODUCTION_GRAPH_TOUCHFULL_WRITE_20260526.md`.
- Neo4j write evidence: `tools\stage7_rewrite\reports\graph_production_promotion_all_full_llm_138102_touchfull_apply_20260526\promotion_report.json`, decision `graph_production_promotion_written`, `ok=true`, mutation counts article/entity/event `138,102/913,082/158,490`.
- Neo4j postwrite evidence: `tools\stage7_rewrite\reports\graph_production_promotion_all_full_llm_138102_touchfull_postverify_20260526\promotion_report.json`, decision `graph_production_promotion_verified`, `ok=true`.
- `tools\stage7_rewrite\scripts\apply_qdrant_role_alias_gate.py` was executed with confirm token for `reports\qdrant_role_alias_gate_legacy_v30_delta10591_138102_20260520`; output `tools\stage7_rewrite\reports\qdrant_role_alias_apply_legacy_v30_delta10591_138102_touchfull_20260526\qdrant_role_alias_apply_report.json`, decision `qdrant_role_alias_apply_complete`, `ok=true`, `applied=false`, action count `0`.
- `tools\stage7_rewrite\scripts\run_qdrant_role_alias_router_smoke.py` verified the alias path at `tools\stage7_rewrite\reports\qdrant_role_alias_router_smoke_legacy_v30_delta10591_138102_touchfull_20260526\qdrant_role_alias_router_smoke.json`, decision `qdrant_role_alias_router_smoke_ready`, `ok=true`.
- Boundary: local Neo4j production marker write happened; local Qdrant service start happened; Qdrant alias apply found no metadata mutation needed. No Qdrant point upsert, raw/source Atlas DB mutation, serving SQLite rebuild/write, public pointer, CloudRun/VPS deploy, mini-program upload/review, memory write, credential read, model/paid API, 9router, or D: root action.

## 2026-05-26 Atlas T5 Fast-Date Repair Attempt

- `tools\stage7_rewrite\scripts\build_atlas_source_ocr_fast_date_repair_attempt.py` consumes `tools\stage7_rewrite\reports\atlas_source_ocr_first_batch_repair_targets_t5_20260526\fast_date_repair_targets.jsonl`, reads Atlas SQLite/source-url sidecar read-only, and emits report-only attempt/accepted/blocked rows under `tools\stage7_rewrite\reports\atlas_source_ocr_fast_date_repair_attempt_t5_20260526`.
- Regression coverage: `tools\stage7_rewrite\tests\test_build_atlas_source_ocr_fast_date_repair_attempt.py`.
- Current real output: `reports\ATLAS_T5_SOURCE_OCR_FAST_DATE_REPAIR_ATTEMPT_20260526.md`, summary decision `atlas_source_ocr_fast_date_repair_attempt_blocked_report_only`, failed checks `[]`, input rows `2`, accepted dates `0`, blocked dates `2`, leak hits `0/0/0`.
- Boundary: report-only fast-date attempt; no OCR/LLM/model execution, graph fact acceptance, source/raw DB mutation, serving SQLite write/rebuild, public pointer, deploy, upload/review, memory, credential, network/model/paid API, destructive Git, 9router, or D: root action.

## 2026-05-26 Atlas T5 First-Batch Repair Targets

- `tools\stage7_rewrite\scripts\build_atlas_source_ocr_first_batch_repair_targets.py` consumes `tools\stage7_rewrite\reports\atlas_source_ocr_first_batch_evidence_probe_t5_20260526\first_batch_evidence_probe_rows.jsonl` and emits report-only target queues under `tools\stage7_rewrite\reports\atlas_source_ocr_first_batch_repair_targets_t5_20260526`.
- Regression coverage: `tools\stage7_rewrite\tests\test_build_atlas_source_ocr_first_batch_repair_targets.py`.
- Current real output: `reports\ATLAS_T5_SOURCE_OCR_FIRST_BATCH_REPAIR_TARGETS_20260526.md`, summary decision `atlas_source_ocr_first_batch_repair_targets_ready_report_only`, failed checks `[]`, repair targets `20`, event-like `7`, fast date lane `2`, date repair `19`, OCR/Markdown repair `18`, entity/review `13`, leak hits `0/0/0`.
- Boundary: report-only target queue; no OCR/LLM/model execution, graph fact acceptance, source/raw DB mutation, serving SQLite write/rebuild, public pointer, deploy, upload/review, memory, credential, network/model/paid API, destructive Git, 9router, or D: root action.

## 2026-05-26 Atlas T5 First-Batch Evidence Probe

- `tools\stage7_rewrite\scripts\probe_atlas_source_ocr_first_batch_evidence.py` consumes `tools\stage7_rewrite\reports\atlas_source_ocr_repair_batch_plan_t5_20260526\first_active_batch.jsonl`, reads the local Atlas SQLite and source-url sidecar read-only, and emits report-only candidate evidence rows under `tools\stage7_rewrite\reports\atlas_source_ocr_first_batch_evidence_probe_t5_20260526`.
- Regression coverage: `tools\stage7_rewrite\tests\test_probe_atlas_source_ocr_first_batch_evidence.py`.
- Current real output: `reports\ATLAS_T5_SOURCE_OCR_FIRST_BATCH_EVIDENCE_PROBE_20260526.md`, summary decision `atlas_source_ocr_first_batch_evidence_probe_ready_report_only`, failed checks `[]`, input rows `20`, article rows found `20`, source-url rows found `20`, source entity rows `306`, event rows `0`, event-like rows `7`, acceptance-ready rows `0`, leak hits `0/0/0`.
- Boundary: report-only local evidence probe; no OCR/LLM/model execution, graph fact acceptance, source/raw DB mutation, serving SQLite write/rebuild, public pointer, deploy, upload/review, memory, credential, network/model/paid API, destructive Git, 9router, or D: root action.

## 2026-05-26 Atlas T5 Source/OCR Repair

- `tools\stage7_rewrite\scripts\build_atlas_source_ocr_repair_packet.py` consumes `tools\stage7_rewrite\reports\atlas_source_context_increment_audit_t5_20260526\high_yield_event_candidates.jsonl` and emits report-only source+OCR, source-context, OCR/Markdown, manual-editorial, and source-rollup queues under `tools\stage7_rewrite\reports\atlas_source_ocr_repair_packet_t5_20260526`.
- Regression coverage: `tools\stage7_rewrite\tests\test_build_atlas_source_ocr_repair_packet.py`.

2026-05-26 00:18 atlas T6 broader source-context recovery overlay: `tools\stage7_rewrite\scripts\build_atlas_social_broader_source_context_recovery_packet.py` is the report-only Q6 selector that consumes current T5 source-context re-extract, OCR/Markdown repair, and participant repair work orders, then emits bounded review slices without promoting source context or enabling writes. Current output is `tools\stage7_rewrite\reports\atlas_social_broader_source_context_recovery_q6_20260526`, with decision `atlas_social_broader_source_context_recovery_ready_report_only`, source-context input/review `1000/120`, OCR/Markdown input/review `1000/80`, participant input/review `968/120`, combined review slice `320`, source-account priority rows `60`, public URL/secret/local-path hits `0/0/0`, and no network/model/paid API, source/raw Atlas DB mutation, serving SQLite rebuild/write, Neo4j/Qdrant/SQLite production write, deploy/upload/review, memory write, secret read, 9router use, or D: root scan. Regression coverage is `tools\stage7_rewrite\tests\test_build_atlas_social_broader_source_context_recovery_packet.py`; latest focused verification is `2 passed`.

2026-05-25 21:12 atlas T5 venue alias/lineage acceptance overlay: `tools\stage7_rewrite\scripts\build_atlas_dj_venue_alias_lineage_acceptance_gate.py` is the report-only Q5 gate that consumes alias candidates plus lineage work orders from the 20:11 follow-up packet, checks the selected serving SQLite read-only, and emits alias-map review-ready rows plus lineage patch/blocked rows without writing an alias map or rebuilding serving SQLite. Current output is `reports\atlas_dj_venue_alias_lineage_acceptance_gate_activity_current_20260525_2111`, with decision `atlas_dj_venue_alias_lineage_acceptance_no_serving_patch_report_only`, alias input groups `2`, alias-map review-ready groups `2`, lineage input rows `45`, lineage patch candidates `0`, lineage blocked rows `45`, serving patch candidates `0`, and no alias-map write, raw/source DB mutation, serving write/rebuild, public pointer, deploy, graph/vector/DB production write, upload/review, memory write, network/model/paid API, secret read, 9router use, or D: root scan. Regression coverage is `tools\stage7_rewrite\tests\test_build_atlas_dj_venue_alias_lineage_acceptance_gate.py`; latest focused verification is `1 passed`.

2026-05-25 18:09 atlas T5 venue acceptance overlay: `tools\stage7_rewrite\scripts\build_atlas_dj_venue_acceptance_gate.py` is the report-only Q5 gate that consumes venue auto candidates, checks source/serving SQLite read-only, and emits accepted/blocked venue patch rows without rebuilding serving SQLite. Current output is `reports\atlas_dj_venue_acceptance_gate_activity_current_20260525_1809`, with decision `atlas_dj_venue_acceptance_no_patch_candidates_report_only`, input rows `932`, patch candidates `0`, blocked rows `304`, already matching rows `628`, existing venue-id conflicts `259`, serving-event-not-found rows `45`, and no raw/source DB mutation, serving write/rebuild, public pointer, deploy, graph/vector/DB production write, upload/review, memory write, network/model/paid API, secret read, 9router use, or D: root scan. Regression coverage is `tools\stage7_rewrite\tests\test_build_atlas_dj_venue_acceptance_gate.py`; latest focused verification is `1 passed`.

2026-05-25 05:57 atlas T6 YYYY identity acceptance overlay: `tools\stage7_rewrite\scripts\build_atlas_social_yyyy_identity_acceptance_gate.py` is the report-only Q6 gate that joins the accepted `YYYY` source-context row with rendered public SoundCloud profile evidence. Current output is `tools\stage7_rewrite\reports\atlas_social_yyyy_identity_acceptance_q6_20260525`, with decision `atlas_social_yyyy_identity_acceptance_ready_report_only`, source rows `1`, rendered rows `1`, identity acceptance passed `1`, blocked rows `0`, accepted entity `YYYY`, accepted_for_graph `0`, identity_proof promotion `0`, avatar/public serving/graph write permissions `0`, and no model/paid API/Neo4j/Qdrant/SQLite/deploy/upload/memory action. Regression coverage is `tools\stage7_rewrite\tests\test_build_atlas_social_yyyy_identity_acceptance_gate.py`; latest focused verification is `2 passed`. Upstream rendered evidence output is `tools\stage7_rewrite\reports\atlas_social_rendered_profile_evidence_yyyy_q6_20260525_0555`.

2026-05-25 04:56 atlas T6 blocked source-context acceptance overlay: `tools\stage7_rewrite\scripts\build_atlas_social_blocked_source_context_acceptance_review.py` is the report-only Q6 gate that consumes the bounded blocked-source-context follow-up rows and candidates, then emits a manual source-context acceptance review without promoting identity or enabling writes. Current output is `tools\stage7_rewrite\reports\atlas_social_blocked_source_context_acceptance_q6_20260525`, with decision `atlas_social_blocked_source_context_acceptance_ready_report_only`, entity rows `2`, candidate rows `8`, manual source-context accepted `1` (`YYYY`), remaining blocked rows `1` (`Cod.Act`), accepted_for_graph `0`, identity_proof promotion `0`, avatar/public serving/graph write permissions `0`, and no network/model/paid API/Neo4j/Qdrant/SQLite/deploy/upload/memory action. Regression coverage is `tools\stage7_rewrite\tests\test_build_atlas_social_blocked_source_context_acceptance_review.py`; latest focused verification is `2 passed`.

2026-05-25 03:54 atlas T6 blocked source-context follow-up overlay: `tools\stage7_rewrite\scripts\build_atlas_social_blocked_source_context_followup.py` is the report-only Q6 gate that consumes the `2` identity acceptance blocked rows and scans bounded repo-local Atlas sidecar files for local source-context candidates. Current output is `tools\stage7_rewrite\reports\atlas_social_blocked_source_context_followup_q6_20260525`, with decision `atlas_social_blocked_source_context_followup_ready_report_only`, selected candidate rows `8`, exact context candidates for `YYYY`, `Cod.Act` still without local source context, accepted_for_graph `0`, identity_proof promotion `0`, avatar/public serving/graph write permissions `0`, and no network/model/paid API/Neo4j/Qdrant/SQLite/deploy/upload/memory action. Regression coverage is `tools\stage7_rewrite\tests\test_build_atlas_social_blocked_source_context_followup.py`; latest focused verification is `3 passed`.

2026-05-25 00:50 atlas Q5/Q6 product-truth mutation overlay: `tools\stage7_rewrite\scripts\build_atlas_social_product_truth_mutation_packet.py` is the report-only mutation-packet builder that consumes `tools\stage7_rewrite\reports\atlas_social_product_truth_promotion_review_q5_q6_20260524\atlas_social_product_truth_promotion_ready.jsonl` and emits explicit local Neo4j staging social-profile edge target selectors, planned metadata mutation Cypher, prewrite/postwrite readback Cypher, and rollback Cypher. Current output is `tools\stage7_rewrite\reports\atlas_social_product_truth_mutation_packet_q5_q6_20260525`, with decision `atlas_social_product_truth_mutation_packet_ready_report_only`, input rows `3`, mutation targets `3`, blocked rows `0`, and no Neo4j/Qdrant/SQLite/public pointer/deploy/upload/memory/network/model/paid API action. Regression coverage is `tools\stage7_rewrite\tests\test_build_atlas_social_product_truth_mutation_packet.py`; latest focused verification is `3 passed`.

2026-05-24 04:33 atlas T6 strict manual acceptance overlay: `tools\stage7_rewrite\scripts\build_atlas_social_strict_manual_acceptance_review.py` is the report-only Q6 gate that joins rendered SoundCloud public-profile evidence with the manual acceptance queue and emits staging-review accepted identity candidates without promoting SoundCloud identity truth or enabling writes. Current output is `tools\stage7_rewrite\reports\atlas_social_strict_manual_acceptance_q6_20260524`, with `3` rendered rows, `3` manual queue rows, `3` strict manual acceptance passed rows, blocked rows `0`, accepted_for_graph `0`, identity_proof promotion `0`, avatar_display_allowed `0`, public_serving_field_allowed `0`, graph_write_allowed `0`, and no network/model/paid API/write/deploy/upload action. Regression coverage is `tools\stage7_rewrite\tests\test_build_atlas_social_strict_manual_acceptance_review.py`; latest focused verification is `2 passed`.

2026-05-24 03:37 atlas T6 rendered profile evidence overlay: `tools\stage7_rewrite\scripts\build_atlas_social_rendered_profile_evidence_packet.py` is the report-only Q6 gate that reads the manual acceptance queue plus bounded SoundCloud metadata and uses OpenCLI public rendering to emit sanitized profile evidence without promoting SoundCloud identity truth. Current output is `tools\stage7_rewrite\reports\atlas_social_rendered_profile_evidence_q6_20260524_0328`, with `3` manual rows, `3` rendered evidence rows, `3` review-ready rows, blocked rows `0`, accepted_for_graph `0`, identity_proof promotion `0`, avatar_display_allowed `0`, public_serving_field_allowed `0`, graph_write_allowed `0`, and no model/paid API/write/deploy/upload action. Regression coverage is `tools\stage7_rewrite\tests\test_build_atlas_social_rendered_profile_evidence_packet.py`; latest focused verification is `2 passed`.

2026-05-24 02:26 atlas T6 identity acceptance-gate overlay: `tools\stage7_rewrite\scripts\build_atlas_social_identity_acceptance_gate.py` is the report-only Q6 gate that reads the source-context review rows and emits a T5/T7 acceptance gate without promoting SoundCloud identity truth. Current output is `tools\stage7_rewrite\reports\atlas_social_identity_acceptance_gate_q6_20260524_0224`, with `5` entity rows, `3` manual acceptance-review-ready rows, `2` blocked rows, accepted_for_graph `0`, identity_proof promotion `0`, avatar_display_allowed `0`, public_serving_field_allowed `0`, graph_write_allowed `0`, and no network/model/paid API/body persistence/write action. Regression coverage is `tools\stage7_rewrite\tests\test_build_atlas_social_identity_acceptance_gate.py`; latest focused verification is `2 passed`.

2026-05-24 01:24 atlas T6 identity source-context overlay: `tools\stage7_rewrite\scripts\build_atlas_social_identity_source_context_review.py` is the report-only Q6 gate that reads the T5/T7 identity-review entity rollups plus the selected local serving SQLite in read-only mode, then emits an Atlas source-context review without promoting SoundCloud identity truth. Current output is `tools\stage7_rewrite\reports\atlas_social_identity_source_context_review_q6_20260524_0124`, with `5` entity rows, `3` entities with Atlas profile/event context, `2` entities still needing Atlas source context, accepted_for_graph `0`, identity_proof promotion `0`, graph_write_allowed `0`, and no network/model/paid API/body persistence/write action. Regression coverage is `tools\stage7_rewrite\tests\test_build_atlas_social_identity_source_context_review.py`; latest focused verification is `2 passed`.

2026-05-24 00:25 atlas T6 identity-review criteria overlay: `tools\stage7_rewrite\scripts\build_atlas_social_identity_review_criteria.py` is the report-only Q6 gate that reads the 2026-05-23 bounded-fetch metadata rows, dedupes target URLs, and emits T5/T7 manual identity-review criteria without promoting graph truth. Current output is `tools\stage7_rewrite\reports\atlas_social_identity_review_criteria_q6_20260524_0028`, with `12` input rows, `10` deduped candidate rows, `5` unique entities, `5` profile metadata manual identity candidates, `5` supporting music-artifact context rows, accepted_for_graph `0`, identity_proof promotion `0`, graph_write_allowed `0`, and no network/model/paid API/body persistence/write action. Regression coverage is `tools\stage7_rewrite\tests\test_build_atlas_social_identity_review_criteria.py`; latest focused verification is `2 passed`.

2026-05-23 22:25 atlas T6 outlink top-review triage overlay: `tools\stage7_rewrite\scripts\build_atlas_social_outlink_top_review_triage.py` is the report-only Q6 gate that reads the 2026-05-23 20:19 `atlas_social_outlink_followup_top_review_queue.jsonl`, dedupes top rows, and emits a bounded next-fetch plan without fetching pages or promoting graph truth. Current output is `tools\stage7_rewrite\reports\atlas_social_outlink_top_review_triage_q6_20260523_2225`, with `80` input rows, `79` deduped rows, `12` selected candidate-only fetch rows, accepted_for_graph `0`, identity_proof promotion `0`, graph_write_allowed `0`, and no network/model/paid API/write action. Regression coverage is `tools\stage7_rewrite\tests\test_build_atlas_social_outlink_top_review_triage.py`; latest focused verification is `2 passed`.

2026-05-23 21:21 atlas T5 production execution-packet overlay: `tools\stage7_rewrite\scripts\build_atlas_serving_production_execution_packet.py` is the report-only rollout/rollback/post-write gate builder for the selected field-repair fullcomplete serving candidate. It reads the candidate DB, manifest, local preflight JSON, API smoke JSON, and browser smoke JSON, emits `reports\atlas_serving_production_execution_packet_20260523_2119\atlas_serving_production_execution_packet.md` / `.json`, records candidate SHA256 `4d61539c24c77c7ad38c2fe561f303b587dba78b9cab958f653f4ce3b2c51974`, and keeps serving pointer update, CloudRun/VPS deploy, Neo4j/Qdrant/SQLite production writes, mini-program upload, memory write, paid API, and secret reads false. Regression coverage is `tools\stage7_rewrite\tests\test_build_atlas_serving_production_execution_packet.py`; latest focused verification is `2 passed`.

2026-05-23 17:20 atlas T5 field-repair promotion overlay: `tools\stage7_rewrite\scripts\build_atlas_field_repair_promotion_sidecar.py` emits the local-only field-repair sidecar at `reports\atlas_field_repair_promotion_sidecar_20260523`, including public-visible time decisions and conservative venue rule additions. `tools\stage7_rewrite\scripts\build_atlas_serving_read_model.py` preserves explicit `public_graph_visible=0` as hidden and can combine the field-repair sidecar with `--participant-delta-accepted-events`. The current selected local candidate is `reports\atlas_serving_field_repair_fullcomplete_strict_20260523-1658\atlas_serving.sqlite`, which supersedes the 15:18 fullcomplete and 16:36 field-repair-only candidates. `services\weekly_activity_cloudrun\src\stage7AtlasSqliteStore.mjs` supports serving read model manifest/overview/search/profile/graph in read-only mode without adding raw/local review schema to serving DBs. Regression coverage is `tools\stage7_rewrite\tests\test_build_atlas_field_repair_promotion_sidecar.py`, `tools\stage7_rewrite\tests\test_build_atlas_serving_read_model.py`, `tools\stage7_rewrite\tests\test_validate_atlas_serving_promotion_preflight.py`, and `services\weekly_activity_cloudrun\tests\stage7SqliteLocal.test.mjs`; latest verification is `7` focused Python tests and `59` CloudRun service tests passing.

2026-05-23 14:59 atlas T5 information-gap overlay: `tools\stage7_rewrite\scripts\build_atlas_serving_information_gap_closure_packet.py` is the local-only gap materializer for the selected DJ-complete activity-aware serving candidate. It reads the serving SQLite plus participant delta, closes the Route B read-model accounting gap, keeps OCRSpan as an upstream contract gap when no per-image spans are exposed, emits full field-gap and participant-delta review queues, reconciles the earlier `546` DJ-event gap into `216` true blocked-event edges plus `330` canonical-normalization-resolved legacy rows, writes `reports\atlas_serving_information_gap_closure_20260523\information_gap_closure.md` / `.json` and `information_gap_review_sidecar.sqlite`, and does not mutate source/serving DBs, deploy, or write graph/vector stores. Regression coverage is `tools\stage7_rewrite\tests\test_build_atlas_serving_information_gap_closure_packet.py`.

2026-05-23 14:37 atlas T5 serving-promotion overlay: `tools\stage7_rewrite\scripts\validate_atlas_serving_promotion_preflight.py` is the report-only local promotion/deploy preflight for the selected DJ-complete activity-aware serving candidate. It validates the chosen `atlas_serving.sqlite` against public table presence, build metadata, forbidden schema/value leaks, hard product/admin noise, activity evidence coverage, normalized-name duplication, graph-window coverage, and optional participant-only comparison. Regression coverage is `tools\stage7_rewrite\tests\test_validate_atlas_serving_promotion_preflight.py`. Current output is `reports\atlas_serving_promotion_preflight_20260523\promotion_preflight.md` / `.json` with decision `promotion_preflight_passed_local_only`; it does not copy DBs, update serving pointers, deploy CloudRun/VPS, or write Neo4j/Qdrant.

2026-05-25 22:18 T1 source-intake static diagnostic: `tools\stage7_rewrite\scripts\build_t1_source_intake_static_diagnostic.py` reads only registry plus existing repo-local queue refresh evidence and writes `reports\ATLAS_T1_SOURCE_INTAKE_STATIC_DIAGNOSTIC_20260525.md` / `reports\t1_source_intake_static_diagnostic_20260525_2218\summary.json`. It is no-secret/report-only and does not call exporter, read cookie/env secrets, scan D:, deploy, upload/review, or mutate Atlas DB/graph/vector state.

2026-05-21 18:03 weekly-thread overlay: the mptext auth path now auto-discovers the latest Docker exporter cookie key from `.mptext-data\kv\cookie`, preferring it over stale `MPTEXT_AUTH_KEY` unless `MPTEXT_AUTH_KEY_PREFER_ENV=1` is set. Entry points are `src\mptext\client.ts`, `src\historyCli.ts`, `src\accounts\runAccountUrlPrefetch.ts`, `src\archive\runMptextArchiveBatch.ts`, `tools\stage7_rewrite\scripts\diagnose_weekly_exporter_session.py`, and `tools\stage7_rewrite\scripts\build_weekly_activity_queue_from_downloads.py`. The weekly pack builder `tools\stage7_rewrite\scripts\archive_old\build_weekly_activity_pack_from_exporter_queue.py` now splits multi-day schedule body sections into same-source child events and keeps `3am 后免费入场` as a time/free-entry rule, not `￥3`. Ping常 evidence and commands are recorded in `docs\weekly-miniprogram-handoff-20260519\PINGCHANG_TWO_ROUTE_HANDOFF_20260521.md`.

2026-05-21 15:15 atlas-thread overlay: `tools\stage7_rewrite\scripts\validate_graph_promotion_readiness.py` now treats missing default historical evidence inputs as a structured report-only blocker (`graph_promotion_blocked_missing_inputs`) instead of crashing with `FileNotFoundError`. Regression coverage is `tools\stage7_rewrite\tests\test_validate_graph_promotion_readiness.py::test_run_reports_missing_default_inputs_without_crashing`; next-gate matrix verification is recorded in `reports\ATLAS_NEXT_GATE_RESILIENCE_TEST_20260521.md`.

2026-05-21 14:40 atlas-thread overlay: current SSOT for Atlas 后半段社交媒体/外部身份搜索 is now `docs\ATLAS_SOCIAL_SEARCH_RULES_SSOT_20260521.md`. The current code mainline is `run_atlas_entity_public_search.py` / `run_atlas_entity_public_search_full_slices.py` -> `build_atlas_entity_public_search_post_filter_queue.py` + `config\atlas_entity_public_search_post_filter_rules.json` -> `fetch_atlas_entity_public_search_content_evidence.py` -> HTTP Fast/OpenCLI/Maigret adapters -> `adjudicate_graph_external_identity_queue.py` / `llm_adjudicate_identity.py`. Older P1 social and 16-row open-source stack scripts remain regression evidence unless this SSOT promotes them.

2026-05-21 14:36 atlas-thread overlay: for **中国地下电子音乐图鉴**, the Atlas subsequent-search Layer D content evidence runner is now implemented at `tools\stage7_rewrite\scripts\fetch_atlas_entity_public_search_content_evidence.py` with tests in `tools\stage7_rewrite\tests\test_fetch_atlas_entity_public_search_content_evidence.py`. It consumes a reduced Post-Filter review queue, supports explicit `dry-run`, `http`, and `scrapling-get` modes, emits report-only content evidence spans, rejects non-public/private URLs, sanitizes sensitive query keys, and keeps `accepted_for_graph=false`, `identity_proof=false`, `graph_write_allowed=false`. Evidence report: `reports\ATLAS_LAYER_D_CONTENT_EVIDENCE_IMPLEMENTATION_20260521.md`; dry-run smoke output: `tools\stage7_rewrite\reports\atlas_entity_public_search_content_evidence_dry_run_20260521`.

2026-05-21 11:02 atlas-thread overlay: for **中国地下电子音乐图鉴**, the `138,102` full-LLM atlas local DB-backed explorer now has a persistent geocode review action console. Code entrypoints are `services\weekly_activity_cloudrun\src\stage7AtlasSqliteStore.mjs` (`geocode_review_actions`, `geocode_review_item_state`, `recordGeocodeReviewAction`, geocode `currentState`), `services\weekly_activity_cloudrun\src\server.mjs` (`POST /api/v1/stage7/local/geocode-review`), `services\weekly_activity_cloudrun\src\atlasLocalPage.mjs` (Geocode Review action buttons and fixed narrow-panel layout), and `tools\stage7_rewrite\scripts\enhance_atlas_sqlite_product_layers.py` (schema source). Targeted tests are `tools\stage7_rewrite\tests\test_enhance_atlas_sqlite_product_layers.py` and `services\weekly_activity_cloudrun\tests\stage7SqliteLocal.test.mjs`. Evidence report is `tools\stage7_rewrite\reports\atlas_geocode_review_actions_138102_20260521\summary.md`; full DB smoke wrote one `review_only` local ledger row and did not promote a map fact or graph/vector edge.

2026-05-21 01:04 atlas-thread overlay: for **中国地下电子音乐图鉴**, the `138,102` full-LLM atlas local SQLite DB-backed explorer now includes a deterministic geocode expansion plus persistent geocode review queue. Code entrypoints remain `tools\stage7_rewrite\scripts\enhance_atlas_sqlite_product_layers.py`, `services\weekly_activity_cloudrun\src\stage7AtlasSqliteStore.mjs`, `services\weekly_activity_cloudrun\src\atlasLocalPage.mjs`, and local routes in `services\weekly_activity_cloudrun\src\server.mjs`. Targeted tests are `tools\stage7_rewrite\tests\test_enhance_atlas_sqlite_product_layers.py` and `services\weekly_activity_cloudrun\tests\stage7SqliteLocal.test.mjs`. Evidence report is `tools\stage7_rewrite\reports\atlas_geocode_review_queue_138102_20260521\summary.md`. The local page is currently served at `http://127.0.0.1:18888/atlas/local`, with `22,109` places, `8,018` geocoded rows, and `14,600` geocode review rows.

2026-05-21 00:45 atlas-thread overlay: for **中国地下电子音乐图鉴**, the `138,102` full-LLM atlas local SQLite DB now has a DB-backed explorer/API, persistent adjudication ledger, and map geocode layer. Code entrypoints are `tools\stage7_rewrite\scripts\enhance_atlas_sqlite_product_layers.py`, `services\weekly_activity_cloudrun\src\stage7AtlasSqliteStore.mjs`, `services\weekly_activity_cloudrun\src\atlasLocalPage.mjs`, and local routes in `services\weekly_activity_cloudrun\src\server.mjs`. Targeted tests are `tools\stage7_rewrite\tests\test_enhance_atlas_sqlite_product_layers.py` and `services\weekly_activity_cloudrun\tests\stage7SqliteLocal.test.mjs`. Evidence reports are `tools\stage7_rewrite\reports\atlas_sqlite_product_layers_138102_20260521` and `tools\stage7_rewrite\reports\atlas_local_db_explorer_138102_20260521`. The local page is currently served at `http://127.0.0.1:18888/atlas/local`.

2026-05-21 00:36 atlas-thread overlay: for **中国地下电子音乐图鉴**, the external identity/network evidence lane now has a report-only public-search runner at `tools\stage7_rewrite\scripts\run_external_identity_public_search.py` with targeted tests in `tools\stage7_rewrite\tests\test_run_external_identity_public_search.py`. It consumes the existing `16` future direct-proof rows, queries local SearXNG, and writes `tools\stage7_rewrite\reports\external_identity_public_search_138102_20260521\public_search_summary.json/.md`, `public_search_queries.jsonl`, `public_search_evidence.jsonl`, `public_search_review.jsonl`, and an intentionally empty `accepted_external_identity_edges_for_graph.jsonl`. Current run output: `48` queries, `207` result rows, `16` candidate-context rows, `accepted_for_graph=0`.

2026-05-21 00:14 atlas-thread overlay: for **中国地下电子音乐图鉴**, the `138,102` full-LLM atlas now has a local full SQLite database product layer at `tools\stage7_rewrite\reports\atlas_local_sqlite_db_138102_20260521\atlas.sqlite`. Code entrypoint is `tools\stage7_rewrite\scripts\build_atlas_local_sqlite_db.py`; targeted tests are `tools\stage7_rewrite\tests\test_build_atlas_local_sqlite_db.py`. The build materializes `articles`, `entities`, `events`, `identity_review_items`, `recommendations`, `graph_rag_answers`, `runtime_reports`, and FTS5 `trigram` search tables from `services\weekly_activity_cloudrun\data\stage7_atlas`. Evidence report is `tools\stage7_rewrite\reports\atlas_local_sqlite_db_138102_20260521\atlas_local_sqlite_db_report.json`.

2026-05-20 23:49 atlas-thread overlay: for **中国地下电子音乐图鉴**, the `138,102` full-LLM atlas now has article/entity/event detail pages remote-effective on CloudRun `weekly-api-038`. Code entrypoints are `services\weekly_activity_cloudrun\src\atlasDetailPage.mjs`, `services\weekly_activity_cloudrun\src\stage7AtlasStore.mjs#getDetail`, `services\weekly_activity_cloudrun\src\server.mjs` routes `/atlas/articles/:id`, `/atlas/entities/:id`, `/atlas/events/:id`, and `/api/v1/stage7/{articles,entities,events}/:id`. `/atlas` links entity/event samples and search results into detail pages. Evidence pack is `tools\stage7_rewrite\reports\atlas_detail_pages_138102_20260520`; remote smoke is `tools\stage7_rewrite\reports\cloudrun_stage7_production_smoke_detail_pages_138102_20260520`.

2026-05-20 21:10 atlas-thread overlay: for **中国地下电子音乐图鉴**, the `138,102` full-LLM atlas now has a remote identity adjudication workbench at `/atlas/identity` on CloudRun `weekly-api-037`. Code entrypoints are `tools\stage7_rewrite\scripts\build_identity_review_workbench.py`, `services\weekly_activity_cloudrun\src\atlasIdentityPage.mjs`, `services\weekly_activity_cloudrun\src\stage7AtlasStore.mjs#getIdentityReview`, and `services\weekly_activity_cloudrun\src\server.mjs` routes `/atlas/identity` plus `/api/v1/stage7/identity-review`. Packaged data is `services\weekly_activity_cloudrun\data\stage7_atlas\identity_review_workbench.json`; evidence pack is `tools\stage7_rewrite\reports\identity_review_workbench_138102_20260520`; remote smoke is `tools\stage7_rewrite\reports\cloudrun_stage7_production_smoke_identity_workbench_138102_20260520`.

2026-05-20 18:58 atlas-thread overlay: for **中国地下电子音乐图鉴**, the `138,102` full-LLM atlas now has a remote browser surface at `/atlas` on CloudRun `weekly-api-035`. Code entrypoints are `services\weekly_activity_cloudrun\src\atlasPage.mjs`, `services\weekly_activity_cloudrun\src\stage7AtlasStore.mjs#getOverview`, and `services\weekly_activity_cloudrun\src\server.mjs` routes `/atlas` plus `/api/v1/stage7/overview`. Current evidence pack is `tools\stage7_rewrite\reports\atlas_browser_ui_138102_20260520`; remote smoke is `tools\stage7_rewrite\reports\cloudrun_stage7_production_smoke_atlas_ui_138102_20260520`.

2026-05-20 07:31 atlas-thread overlay: for **中国地下电子音乐图鉴**, the `138,102` full-LLM atlas base is now remote-effective on CloudRun `weekly-api-034`. The current product-surface evidence pack is `tools\stage7_rewrite\reports\atlas_final_product_surface_138102_20260520`; deploy evidence is `tools\stage7_rewrite\reports\cloudrun_direct_api_stage7_atlas_138102_20260520\cloudrun_direct_api_deploy_report.json`; Stage7 production smoke is `tools\stage7_rewrite\reports\cloudrun_stage7_production_smoke_138102_20260520\cloudrun_stage7_production_smoke.json`. Qdrant current aliases required no mutation in this slice because `qdrant_role_alias_gate_legacy_v30_delta10591_138102_20260520` planned `0` actions and `qdrant_role_alias_apply_legacy_v30_delta10591_138102_20260520` applied `0` actions; alias-path smoke is ready. The service exposes the atlas through `/api/v1/stage7/*`; search remains `materialized_text_scan`, and vector status is report-backed.

2026-05-20 07:05 atlas-thread overlay: for **中国地下电子音乐图鉴**, current stable/product/Neo4j/vector-complete truth is `138,102` articles after `reports\atlas_full_llm_inventory_20260520` promoted the legacy v30 `10,591` already-DeepSeek-processed delta into `reports\stable_merge_all_full_llm_runs_127511_plus_legacy_v30_10591_20260520` and `reports\vector_cuda_completion_legacy_v30_delta10591_138102_20260520` completed the role-isolated Qdrant vectors through WSL CUDA. The current consumer pack is `reports\consumer_release_pack_all_full_llm_runs_138102_20260520`; Neo4j verify is `reports\graph_production_promotion_all_full_llm_138102_verify_20260520`; vector router smoke is `reports\vector_collection_router_smoke_legacy_v30_delta10591_138102_cuda_20260520`; local product package is `services\weekly_activity_cloudrun\data\stage7_atlas`.

2026-05-20 atlas-thread overlay: for **中国地下电子音乐图鉴**, read `docs\ELECTRONIC_MUSIC_GRAPH_CURRENT_AUTHORITY_20260518.md`, `docs\ELECTRONIC_MUSIC_GRAPH_PIPELINE_STAGE_MAP_20260518.md`, `tools\stage7_rewrite\reports\stable_merge_all_deepseek_127490_plus_oldroute_retry21_20260520\stable_merge_summary.md`, `tools\stage7_rewrite\reports\consumer_release_pack_all_deepseek_127511_20260520\manifest.md`, `tools\stage7_rewrite\reports\graph_production_promotion_all_deepseek_127511_verify_20260520\promotion_report.md`, `tools\stage7_rewrite\reports\vector_collection_router_smoke_oldroute_retry21_20260520\vector_collection_router_smoke.md`, `tools\stage7_rewrite\reports\atlas_residual_gap_packet_127511_20260520\atlas_residual_gap_packet.md`, `tools\stage7_rewrite\reports\atlas_full_source_lineage_47k_93k_gap_20260519\atlas_full_source_lineage.md`, and `tools\stage7_rewrite\reports\atlas_gap_backfill_execution_packet_20260519\gap_backfill_execution_packet.md` before using the older structured map below. This paragraph is previous-vector-base context: `127,511` is historical after the 07:05 `138,102` vector-complete overlay above. The current residual packet has `3,497` gated non-waste rows. Stage7 is one large production stage inside the whole pipeline. The current full-stage order is source discovery -> archive/mptext/assets/Dajiala -> OCR/Markdown -> LLM text extraction -> Stage7 structured extraction -> graph marker -> 1024-d isolated vector lanes -> external network/social evidence -> QA/orchestration -> downstream consumers. The source-lineage runner is `tools\stage7_rewrite\scripts\build_atlas_full_source_lineage.py`; the current residual runner is `tools\stage7_rewrite\scripts\build_atlas_residual_gap_packet_127511.py`; the historical residual no-rerun/hold/gated-backfill runner is `tools\stage7_rewrite\scripts\build_atlas_gap_backfill_execution_packet.py`; the P3 source-context decision runner is `tools\stage7_rewrite\scripts\build_external_identity_source_context_decision_packet.py`; Qdrant role alias production apply is `tools\stage7_rewrite\scripts\apply_qdrant_role_alias_gate.py`; post-apply alias-path smoke is `tools\stage7_rewrite\scripts\run_qdrant_role_alias_router_smoke.py`.

2026-05-17 refresh note: the structured map below remains the 2026-05-07 generated map. Latest verification lives in `C:\code\githubstar\wechathtmldownload\docs\current-runtime.md`: weekly Python tests passed, aggregate Dajiala fallback tests passed, and `weekly_activity_next_week_pipeline.ps1` parsed/dry-ran for a 15-day window. The weekly mini-program lane now uses `weekly_activity_next_week_pipeline.ps1` Step 3.6 to block aggregate parents, fetch secondary links through mptext with Dajiala `article_detail` as a configured fallback, then run DeepSeek Pro source-grounded child-event extraction.

## 2026-05-07 Active Additions

- `src/artifacts/finalizeLlmPack.ts`: `finalize-llm-pack` still scans the main artifact root by default and can additively include a bounded `--intakeManifestPath` for multi-root recovered/review artifact dirs. It also supports `--intakeOnly --limit N` for canary releases that must avoid recursively scanning the main D: artifact root.
- `tools/stage7_rewrite/scripts/build_llm_intake_manifest.py`: builds `LLM_INTAKE_MANIFEST_20260507` from known recovered/review queues, including full-empty recovery `PROCESS_WAVE_*` outputs, without scanning D: roots.
- `tools/stage7_rewrite/scripts/build_full_empty_recovery_wave.py`: builds account-balanced full-empty recovery waves and now excludes prior `FULL_EMPTY_LINK_RECOVERY_*/SHORT2LONG_WAVE_*` attempts to prevent duplicate paid short2long spending.
- `tools/stage7_rewrite/scripts/build_weekly_activity_queue.py`: builds since-cursor weekly activity candidate queues from a bounded latest prefetch and historical queue, without fetching pages or scanning D: roots.
- `tools/stage7_rewrite/scripts/build_weekly_activity_recommendation_pack.py`: builds a file-only weekly activity recommendation pack from bounded weekly queue rows and Stage7 `llm_extract` outputs; it writes articles/events/entities/candidates/unmatched/summary files without fetching pages or writing vector/graph/database targets.
- `tools/stage7_rewrite/scripts/build_weekly_activity_miniprogram_api.py`: builds static mini-program JSON routes from the weekly recommendation pack, including `current.json`, `by-city/*.json`, `by-date/*.json`, and `by-id/*.json`, without fetching pages or writing vector/graph/database targets.
- `tools/stage7_rewrite/scripts/expand_weekly_aggregate_articles.py`: blocks aggregate parent articles, extracts parent-body/secondary-link child events with DeepSeek Pro, and can use Dajiala `article_detail` as a bounded content fallback after mptext/exporter fails or returns too little text.
- `tools/stage7_rewrite/weekly_activity_next_week_pipeline.ps1`: current 15-day weekly mini-program release generator; imports relevant Windows runtime env vars into the process without logging secret values, then runs aggregate expansion, API build, duplicate/conflict repair, field repair, and strict cross-source audit.
- `tools/stage7_rewrite/scripts/run_stage8_write_strategy_tests.py`: bounded existing-data Stage8/Stage9 write strategy tester. It builds vector jobs, calls Mac 11437 for embeddings, writes `wechat_test_*` Qdrant collections, writes an isolated PC SQLite ledger, and reports Neo4j reachability without touching production collections or `pipeline.sqlite`.
- `apps/weekly_activity_miniprogram`: WeChat mini-program MVP shell for the weekly activity guide; it calls the `weekly-api` contract and does not depend on CloudBase database schema.
- `services/weekly_activity_cloudrun`: CloudBase Run compatible stateless Node HTTP service for `GET /api/v1/weekly/*`, backed by the static mini-program JSON release for the local MVP.
- `tools/stage7_rewrite/scripts/run-93k-stage-orchestrator.ps1`: post-OCR release phase now passes `--intakeManifestPath` so latest free/short2long/Dajiala recovered outputs are not lost before LLM canary.
- `tools/stage7_rewrite/stage7/audit_inputs.py`: Stage7 input audit now discovers article directories recursively by `llm_input.md`, so nested release layouts such as `source/account/token` are accepted.
- `tools/stage7_rewrite/scripts/run-full-empty-wave-supervisor.ps1`: historical empty-link supervisor resumes disk-paused free processing from `chunk-runner-status.json.next_chunk`.
- `tools/stage7_rewrite/scripts/show_93k_pipeline_status.py`: read-only status now includes watchdog, OCR, orchestrator, full-empty wave, weekly activity lane, weekly recommendation pack, mailroom, and red/amber flags.
- `tools/stage7_rewrite/config/vector_endpoints.yaml`: Stage8 vector routing now names `local_mac_vector_endpoint_11437` as the default 93k WeChat entity/event/relation endpoint, with Mac-local `canonical_url` and PC runtime `pc_call_url`.
- `tools/stage7_rewrite/stage7/vector_plan/build_embedding_jobs.py`: generated vector jobs now carry endpoint id, endpoint port, route role, canonical URL, PC call URL, and expected dimension in metadata.

## Package scripts

| Script | Command |
| --- | --- |
| archive-article | tsx src/cli.ts archive-article |
| archive-batch | tsx src/cli.ts archive-batch |
| audit-archive-run | tsx src/cli.ts audit-archive-run |
| build | tsc -p tsconfig.json |
| calibrate:qwen3.6 | node tools/runQwenCalibrationSweep.mjs |
| dajiala-repair-archive-batch | tsx src/cli.ts dajiala-repair-archive-batch |
| dist:win | npm run stage:runtime && npm run build && electron-builder --win portable |
| dist:win:signed | node tools/checkWindowsSigningEnv.mjs && npm run stage:runtime && npm run build && electron-builder --win portable -c.win.signAndEditExecutable=true -c.win.forceCodeSigning=true |
| download-archive-assets | tsx src/cli.ts download-archive-assets |
| download-archive-assets-batch | tsx src/cli.ts download-archive-assets-batch |
| eval:downstream-matrix | node tools/runDownstreamEvalMatrix.mjs |
| export-llm-batch | tsx src/cli.ts export-llm-batch |
| export-markitdown-batch | tsx src/cli.ts export-markitdown-batch |
| export:rawwechat-llm | tsx src/cli.ts export-llm-batch --inputDir D:/rawwechat --outDir D:/rawwechat_llm_artifacts --mirrorDir D:/rawwechat_llm_md --statusPath D:/rawwechat_llm_artifacts/batch-status.json --resume |
| export:rawwechat-llm-artifacts | tsx src/cli.ts process-batch --inputDir D:/rawwechat --outDir D:/rawwechat_llm_artifacts --statusPath D:/rawwechat_llm_artifacts/batch-status.json --resume |
| export:rawwechat-md | tsx src/cli.ts export-markitdown-batch --inputDir D:/rawwechat --outDir D:/rawwechat_md --statusPath D:/rawwechat_md/markitdown-batch-status.json --resume |
| extract-incomplete-archive-queue | tsx src/cli.ts extract-incomplete-archive-queue |
| fetch-history-urls | tsx src/historyCli.ts |
| filter-dajiala-repair-candidates | tsx src/cli.ts filter-dajiala-repair-candidates |
| finalize-llm-pack | tsx src/cli.ts finalize-llm-pack |
| mirror:rawwechat-llm-md | node tools/mirrorLlmInputTree.mjs D:/rawwechat_llm_artifacts D:/rawwechat_llm_md |
| mptext-archive-batch | tsx src/cli.ts mptext-archive-batch |
| ocr-poster-batch | tsx src/cli.ts ocr-poster-batch |
| pcui:electron-perf | electron tools/runPcuiElectronPerfTrace.mjs |
| pcui:image:generate | node tools/generatePcuiGptImage2Shots.mjs --execute --include-master |
| pcui:image:generate:responses | node tools/generatePcuiGptImage2Shots.mjs --execute --include-master --api responses-tool |
| pcui:image:prompts | node tools/generatePcuiGptImage2Shots.mjs --dry-run --include-master |
| pcui:image:verify | node tools/generatePcuiGptImage2Shots.mjs --verify-only |
| pcui:image:verify:responses | node tools/generatePcuiGptImage2Shots.mjs --verify-only --api responses-tool |
| pcui:interact | electron tools/runPcuiInteractionHarness.mjs |
| pcui:perf | node tools/runPcuiPerformanceHarness.mjs |
| pcui:state-matrix | node tools/runPcuiStateMatrix.mjs |
| pcui:ui-audit | node tools/runPcuiUiAudit.mjs |
| prefetch-account-urls | tsx src/cli.ts prefetch-account-urls |
| process-article | tsx src/cli.ts process-article |
| process-batch | tsx src/cli.ts process-batch |
| process-dual-track | tsx src/cli.ts process-dual-track |
| run-downstream-llm | tsx src/cli.ts run-downstream-llm |
| run-downstream-llm-batch | tsx src/cli.ts run-downstream-llm-batch |
| run-keeper | tsx src/cli.ts run-keeper |
| shot:gui | npm run build && electron tools/capturePcuiScreenshot.mjs |
| shot:gui:runtime | npm run build && node tools/capturePcuiRuntimeScreenshot.mjs |
| stage:runtime | node tools/stageMarkitdownRuntime.mjs |
| start:gui | npm run build && electron . |
| test | tsx --test tests/**/*.test.ts |
| verify:runtime-import | npm run build && node tools/verifyDesktopRuntimeImport.mjs |
| watch:archive-assets | node tools/watchArchiveStatus.mjs D:/DDownload/_archive_mptext/asset-retention-status.json 5000 |
| watch:mptext-archive | node tools/watchArchiveStatus.mjs D:/DDownload/_archive_mptext/mptext-archive-status.json 5000 |
| watch:rawwechat-llm | node tools/watchMarkitdownBatchStatus.mjs D:/rawwechat_llm_artifacts/batch-status.json |
| watch:rawwechat-md | node tools/watchMarkitdownBatchStatus.mjs D:/rawwechat_md/markitdown-batch-status.json |
| weekly-api:start | node services/weekly_activity_cloudrun/src/server.mjs |
| weekly-api:test | node --test services/weekly_activity_cloudrun/tests/*.test.mjs |

## CLI commands from `src/cli.ts`

| CLI command | Package script coverage |
| --- | --- |
| archive-article | archive-article |
| archive-batch | archive-batch, mptext-archive-batch, dajiala-repair-archive-batch |
| audit-archive-run | audit-archive-run |
| build-graph-candidate-pack | direct via `tsx src/cli.ts build-graph-candidate-pack` |
| create-runner-job-pack | direct via `tsx src/cli.ts create-runner-job-pack` |
| dajiala-repair-archive-batch | dajiala-repair-archive-batch |
| download-archive-assets | download-archive-assets, download-archive-assets-batch |
| download-archive-assets-batch | download-archive-assets-batch |
| export-llm-batch | export-llm-batch, export:rawwechat-llm |
| export-markitdown-batch | export-markitdown-batch, export:rawwechat-md |
| extract-incomplete-archive-queue | extract-incomplete-archive-queue |
| filter-dajiala-repair-candidates | filter-dajiala-repair-candidates |
| finalize-llm-pack | finalize-llm-pack |
| ignuke-dry-run-import | direct via `tsx src/cli.ts ignuke-dry-run-import` |
| mptext-archive-batch | mptext-archive-batch |
| ocr-poster-batch | ocr-poster-batch |
| prefetch-account-urls | prefetch-account-urls |
| process-article | process-article |
| process-batch | process-batch, export:rawwechat-llm-artifacts |
| process-dual-track | process-dual-track |
| register-pack | direct via `tsx src/cli.ts register-pack` |
| run-downstream-llm | run-downstream-llm, run-downstream-llm-batch |
| run-downstream-llm-batch | run-downstream-llm-batch |
| run-keeper | run-keeper |
| split-manifest-shards | direct via `tsx src/cli.ts split-manifest-shards` |
| validate-runner-result-pack | direct via `tsx src/cli.ts validate-runner-result-pack` |

## Source areas

| Area | TS files |
| --- | --- |
| accounts | 2 |
| api | 1 |
| archive | 11 |
| artifacts | 4 |
| cli.ts | 1 |
| dajiala | 1 |
| desktop | 3 |
| extract | 11 |
| graph | 1 |
| historyCli.ts | 1 |
| ignuke | 1 |
| llm | 2 |
| mptext | 1 |
| ops | 3 |
| orchestrator | 3 |
| packs | 2 |
| pipeline | 10 |
| poster | 2 |
| runners | 1 |
| stage | 2 |
| state | 7 |
| types.ts | 1 |
| utils | 13 |

## Current longrun control scripts

| Script | Purpose |
| --- | --- |
| `tools\stage7_rewrite\scripts\run-latest-free-archive-chunks.ps1` | Recent-post free archive/assets/process/audit chunk runner with blocked-quality gates. |
| `tools\stage7_rewrite\scripts\run-latest-free-overnight.ps1` | Unattended controller that resumes recent free chunks in small rounds. |
| `tools\stage7_rewrite\scripts\run-ocr-imageheavy-chunks.ps1` | Chunked OCR recovery runner for image-heavy artifacts. |
| `tools\stage7_rewrite\scripts\run-night-watchdog.ps1` | Night watchdog for recent free chunks, OCR, mailroom heartbeat, forbidden process detection, and optional bounded Dajiala canary. Full historical empty-link recovery is a separate quality-gated lane. |
| `tools\stage7_rewrite\scripts\run-93k-stage-orchestrator.ps1` | Post-OCR staged controller for release candidate build, Stage7 LLM canary, entity quality, vector JSONL canary, graph candidate pack, and guarded batch50. |
| `tools\stage7_rewrite\scripts\show_93k_pipeline_status.py` | Read-only 93k longrun status aggregator; writes current watchdog/OCR/orchestrator/quality/ETA report without scanning D: roots. |
| `tools\stage7_rewrite\scripts\stage7_quality_report.py` | Stage7 entity/event/relation quality report from extraction output only; flags empty evidence and low-entity outputs. |
| `tools\stage7_rewrite\scripts\stage8_vector_quality_report.py` | Stage8 embedding JSONL quality report; validates dimensions, failures, object kinds, and non-finite vector values. |
| `tools\stage7_rewrite\scripts\run_stage8_write_strategy_tests.py` | Existing-data canary for Stage8/Stage9 write strategies; compares Qdrant split-by-kind vs unified test collections, writes an isolated PC SQLite ledger, and probes Neo4j reachability. |
| `tools\stage7_rewrite\scripts\build_weekly_activity_recommendation_pack.py` | Offline weekly activity pack builder; joins weekly queue rows to Stage7 extracts and emits recommendation candidates only from real extracted evidence. |
| `tools\stage7_rewrite\scripts\build_weekly_activity_miniprogram_api.py` | Static JSON interface builder for the weekly activity mini-program MVP; consumes only main recommendation candidates. |
| `tools\stage7_rewrite\config\vector_endpoints.yaml` | Stage8 endpoint registry; defaults 93k entity/event/relation jobs to `local_mac_vector_endpoint_11437`. |

## Source files

- `src/accounts/accountInventory.ts`
- `src/accounts/runAccountUrlPrefetch.ts`
- `src/api/fetchHistoryUrls.ts`
- `src/archive/archiveArticle.ts`
- `src/archive/articleHtmlQuality.ts`
- `src/archive/downloadArticleAssets.ts`
- `src/archive/extractIncompleteArchiveQueue.ts`
- `src/archive/filterDajialaRepairCandidates.ts`
- `src/archive/normalizeArticleToken.ts`
- `src/archive/runArchiveBatch.ts`
- `src/archive/runAssetDownloadBatch.ts`
- `src/archive/runDajialaArchiveRepairBatch.ts`
- `src/archive/runMptextArchiveBatch.ts`
- `src/archive/types.ts`
- `src/artifacts/finalizeLlmPack.ts`
- `src/artifacts/pathSafety.ts`
- `src/artifacts/runArchiveAudit.ts`
- `src/artifacts/types.ts`
- `src/cli.ts`
- `src/dajiala/client.ts`
- `src/desktop/runtimeCapture.ts`
- `src/desktop/runtimeImport.ts`
- `src/desktop/runtimeVerification.ts`
- `src/extract/buildBackgroundRecall.ts`
- `src/extract/buildCleanMd.ts`
- `src/extract/buildLlmInputMd.ts`
- `src/extract/buildSidecar.ts`
- `src/extract/cleanLlmContent.ts`
- `src/extract/cleanMarkitdown.ts`
- `src/extract/extractAssets.ts`
- `src/extract/extractBody.ts`
- `src/extract/extractFooterInfo.ts`
- `src/extract/extractMeta.ts`
- `src/extract/parseHtml.ts`
- `src/graph/graphCandidatePack.ts`
- `src/historyCli.ts`
- `src/ignuke/dryRunImport.ts`
- `src/llm/runDownstreamLlmBatch.ts`
- `src/llm/runDownstreamLlmStage.ts`
- `src/mptext/client.ts`
- `src/ops/archiveAssetRunGuard.ts`
- `src/ops/archiveRunGuard.ts`
- `src/ops/liveStageLock.ts`
- `src/orchestrator/buildBatchProjection.ts`
- `src/orchestrator/pipelineKeeper.ts`
- `src/orchestrator/stageRunners.ts`
- `src/packs/checksums.ts`
- `src/packs/packRegistry.ts`
- `src/pipeline/artifactManifest.ts`
- `src/pipeline/processArchiveBundleDualTrack.ts`
- `src/pipeline/processArticle.ts`
- `src/pipeline/processArticleDualTrack.ts`
- `src/pipeline/runDualTrackBatch.ts`
- `src/pipeline/runLlmExportBatch.ts`
- `src/pipeline/runMarkitdownBatch.ts`
- `src/pipeline/shardLock.ts`
- `src/pipeline/shardManifest.ts`
- `src/pipeline/writeDualTrackArtifacts.ts`
- `src/poster/runPosterOcrBatch.ts`
- `src/poster/runPosterOcrFallback.ts`
- `tools/auditPosterOcrRecoveryList.mjs`
- `tools/buildRecaptureQueueFromArtifacts.mjs`
- `tools/stage7_rewrite/scripts/run-recapture-asset-chunks.ps1`
- `src/runners/runnerPack.ts`
- `src/stage/contracts.ts`
- `src/stage/stageManifest.ts`
- `src/state/downloadQueueStore.ts`
- `src/state/jobStore.ts`
- `src/state/jobStoreFile.ts`
- `src/state/jobTypes.ts`
- `src/state/pipelineProjection.ts`
- `src/state/pipelineStore.ts`
- `src/state/sqlitePipelineStore.ts`
- `src/types.ts`
- `src/utils/abort.ts`
- `src/utils/dom.ts`
- `src/utils/fileDiscovery.ts`
- `src/utils/fs.ts`
- `src/utils/hash.ts`
- `src/utils/jsonl.ts`
- `src/utils/markitdown.ts`
- `src/utils/markitdownWorker.ts`
- `src/utils/queueExecutor.ts`
- `src/utils/regex.ts`
- `src/utils/rustSidecar.ts`
- `src/utils/snapshotCompaction.ts`
- `src/utils/text.ts`

## Tests

| Test file |
| --- |
| tools/stage7_rewrite/tests/test_weekly_activity_recommendation_pack.py |
| tools/stage7_rewrite/tests/test_weekly_activity_miniprogram_api.py |
| tests/accountInventory.test.ts |
| tests/archiveAssetRunGuard.test.ts |
| tests/archiveAudit.test.ts |
| tests/archiveArticle.test.ts |
| tests/archiveBatch.test.ts |
| tests/archiveModeBatch.test.ts |
| tests/archiveRunGuard.test.ts |
| tests/articleHtmlQuality.test.ts |
| tests/artifactManifest.test.ts |
| tests/buildLlmInputMd.test.ts |
| tests/cleanMarkitdown.test.ts |
| tests/dajialaArchiveRepairBatch.test.ts |
| tests/dajialaClient.test.ts |
| tests/downloadArticleAssets.test.ts |
| tests/extractBody.test.ts |
| tests/extractFooterInfo.test.ts |
| tests/extractIncompleteArchiveQueue.test.ts |
| tests/extractMeta.test.ts |
| tests/fetchHistoryUrls.test.ts |
| tests/filterDajialaRepairCandidates.test.ts |
| tests/finalizeLlmPack.test.ts |
| tests/fsUtils.test.ts |
| tests/graphCandidatePack.test.ts |
| tests/jobStore.test.ts |
| tests/liveStageLock.test.ts |
| tests/markitdownWorker.test.ts |
| tests/mptextArchiveBatch.test.ts |
| tests/mptextClient.test.ts |
| tests/packRegistry.test.ts |
| tests/pcuiAuditProjection.test.ts |
| tests/pcuiContract.test.ts |
| tests/pcuiImagePromptWorkflow.test.ts |
| tests/pcuiRendererModules.test.ts |
| tests/pcuiRuntimeGuards.test.ts |
| tests/pcuiShellStructure.test.ts |
| tests/perfHarness.test.ts |
| tests/pipelineKeeper.test.ts |
| tests/pipelineProjection.test.ts |
| tests/pipelineStore.test.ts |
| tests/posterOcrFallback.test.ts |
| tests/processArchiveBundle.test.ts |
| tests/queueExecutor.test.ts |
| tests/runAccountUrlPrefetch.test.ts |
| tests/runDownstreamLlm.test.ts |
| tests/runDownstreamLlmBatch.test.ts |
| tests/runDualTrackBatch.test.ts |
| tests/runLlmExportBatch.test.ts |
| tests/runMarkitdownBatch.test.ts |
| tests/runPosterOcrBatch.test.ts |
| tests/runnerPack.test.ts |
| tests/runtimeCapture.test.ts |
| tests/runtimeImport.test.ts |
| tests/rustGolden.test.ts |
| tests/rustSidecar.test.ts |
| tests/shardLock.test.ts |
| tests/shardManifest.test.ts |
| tests/sqlitePipelineStore.test.ts |
| tests/stageContracts.test.ts |
| tests/stageManifest.test.ts |

## Desktop / PCUI files

| Desktop file |
| --- |
| desktop/pcuiAnomalies.js |
| desktop/pcuiAppState.js |
| desktop/pcuiAuditProjection.js |
| desktop/pcuiCommandDispatch.js |
| desktop/pcuiConsoleDom.js |
| desktop/pcuiContextMenuController.js |
| desktop/pcuiContract.js |
| desktop/pcuiDomRefs.js |
| desktop/pcuiFormat.js |
| desktop/pcuiInspectorController.js |
| desktop/pcuiInspectorDom.js |
| desktop/pcuiKeyboardController.js |
| desktop/pcuiPerfMarks.js |
| desktop/pcuiPersistedState.js |
| desktop/pcuiProjectionCache.js |
| desktop/pcuiRefreshGuards.js |
| desktop/pcuiRootProfileController.js |
| desktop/pcuiRuntimeGuards.js |
| desktop/pcuiSearchIndex.js |
| desktop/pcuiSelectionController.js |
| desktop/pcuiShellDom.js |
| desktop/pcuiSnapshotAdapters.js |
| desktop/pcuiSnapshotDiff.js |
| desktop/pcuiStatusbarController.js |
| desktop/pcuiTableDom.js |
| desktop/pcuiThemeController.js |
| desktop/pcuiVirtualListDom.js |
| desktop/pcuiVirtualTable.js |
| desktop/pcuiWorkspaceControllers.js |
| desktop/pcuiWorkspaceModel.js |
| desktop/pcuiWorkspaceRows.js |
| desktop/renderer.js |
| desktop/main.mjs |
| desktop/preload.cjs |
| desktop/index.html |
| desktop/styles.css |

## Tools

- `tools/analyzeGithubProjectRecommendations.mjs`
- `tools/analyzeNoneBackend.mjs`
- `tools/capturePcuiRuntimeScreenshot.mjs`
- `tools/capturePcuiScreenshot.mjs`
- `tools/checkOcrQualitySample.mjs`
- `tools/checkWindowsSigningEnv.mjs`
- `tools/exportMptextAccount.mjs`
- `tools/generatePcuiGptImage2Shots.mjs`
- `tools/githubProjectRecoExperiment.mjs`
- `tools/mirrorLlmInputTree.mjs`
- `tools/model-compare.mjs`
- `tools/pcuiGptImage2Prompts.mjs`
- `tools/pcuiRuntimeEvidenceManifest.mjs`
- `tools/queue-downstream-batch.mjs`
- `tools/repairCorruptedOcr.mjs`
- `tools/repairNoneBackendBatch.mjs`
- `tools/runDownstreamEvalMatrix.mjs`
- `tools/runPcuiElectronPerfTrace.mjs`
- `tools/runPcuiInteractionHarness.mjs`
- `tools/runPcuiPerformanceHarness.mjs`
- `tools/runPcuiStateMatrix.mjs`
- `tools/runPcuiUiAudit.mjs`
- `tools/runQwenCalibrationSweep.mjs`
- `tools/sample-downstream.mjs`
- `tools/stageMarkitdownRuntime.mjs`
- `tools/verifyDesktopRuntimeImport.mjs`
- `tools/watchArchiveStatus.mjs`
- `tools/watchExportBatch.mjs`
- `tools/watchMarkitdownBatchStatus.mjs`

## 2026-05-31 Atlas / HUAIDJ Active Slice

- Longrun manifest: `docs\longrun\atlas-route-external-db-20260531\manifest.md`.
- Command ledger: `reports\WEEKLY_USER_COMMAND_RECALL_EXECUTION_LEDGER_20260531.md`.
- Week/month mini-program preview: `apps\weekly_activity_miniprogram\utils\datePreview.js` plus `pages\index\index.*`.
- DJ Interview review queue: `services\weekly_activity_cloudrun\src\interviewStore.mjs` and `services\weekly_activity_cloudrun\src\server.mjs` expose redacted `GET /api/v1/atlas/dj-interviews/review-queue`.
- DJ Interview review packet builder: `services\weekly_activity_cloudrun\src\interviewReviewPacket.mjs` and `services\weekly_activity_cloudrun\scripts\build_dj_interview_review_packet.mjs`.
- DJ Interview review workbench: `services\weekly_activity_cloudrun\src\interviewReviewWorkbench.mjs` and `services\weekly_activity_cloudrun\scripts\build_dj_interview_review_workbench.mjs` generate redacted local HTML from the review packet.
- DJ Interview intake: `services\weekly_activity_cloudrun\src\interviewIntake.mjs`, `services\weekly_activity_cloudrun\scripts\import_dj_interview_submissions.mjs`, and `services\weekly_activity_cloudrun\templates\dj_interview_intake_template.md` import consented local Markdown/JSON/JSONL interview drafts into the private sidecar.
- Mini-program external-link action: `apps\weekly_activity_miniprogram\utils\externalLinkAction.js` plus `pages\interview\interview.*` copy mixtape/Instagram original links and reject direct media URLs before submit; report `reports\WEEKLY_MINIPROGRAM_EXTERNAL_LINK_ACTION_S28_20260531.md`.
- Mini-program event-handler coverage: `apps\weekly_activity_miniprogram\tests\page-event-handler-coverage.test.cjs` scans every `app.json` page and verifies static WXML `bind*` / `catch*` handlers resolve to page JS methods; `share-wiring.test.cjs` derives share coverage from `app.json`. S29 local preflight output is `tools\stage7_rewrite\reports\weekly_deploy_upload_preflight_s29_20260531\weekly_deploy_upload_preflight.json`, and post-S29 CodeGraph pending is `0/0/0`.
- Atlas relation-field integrity guard: `tools\stage7_rewrite\scripts\audit_atlas_relation_field_integrity.py` checks DB2/DB3 DJ-DJ, DJ-venue, source-ref, ID, and empty-overwrite boundaries.
- Weekly deploy/upload preflight: `tools\stage7_rewrite\scripts\run_weekly_deploy_upload_preflight.py` and `npm run weekly:deploy-upload:preflight` run the relation guard, backend tests, and every `apps\weekly_activity_miniprogram\tests\*.test.cjs` mini-program static test without deploying, uploading, reading keys, or writing data.
- DevTools protocol audit: `reports\WEEKLY_MINIPROGRAM_DEVTOOLS_CURRENT_CLI_PROTOCOL_AUDIT_20260531.md`.
- Current rendered mini-program automation finding: `miniprogram-automator@0.12.1` opens a bare dynamic-port WebSocket, while current WeChat DevTools CLI requires a CLI subprotocol plus additional long-connection initialization. Pure Node/static tests and clean-CI quality remain the active mobile gate.
- External music direct-media guard: `services\weekly_activity_cloudrun\src\externalMusicLinks.mjs` rejects common direct audio/video file URLs and keeps music/mixtape as original-platform outlinks.
- Source URL map package guard: `apps\weekly_activity_miniprogram\project.config.json` ignores `source_actions`, and `page-source-routing.test.cjs` asserts the full source URL map is not bundled.
- Tencent signature audit: `reports\WEEKLY_TENCENT_GEOCODE_SIGNATURE_AUDIT_20260531.md`; current status `111` is a credential/control-plane blocker, not a proven local signing algorithm bug.
- Rust Club provider retry: `reports\WEEKLY_RUST_CLUB_PROVIDER_RETRY_S20_20260531.md`; Amap key is callable but returns `strong_place_matches=0`, so coordinates remain unwritten.

## Profiles

| Profile |
| --- |
| profiles/qwen36_27b_4090_llama_specdec_winning_candidate.json |
| profiles/qwen36_27b_4090_longctx_experimental.json |
| profiles/qwen36_27b_4090_stage7_default.json |
| profiles/qwen36_27b_4090_stage7_safe.json |

## Python/stage scripts

- `scripts/stage7/run_canary_v4.py`
- `scripts/stage7_chunker.py`
- `scripts/stage7_postprocess_output.py`
- `scripts/stage7_validate_outputs.py`
- `tools/stage7_rewrite/scripts/build_llm_intake_manifest.py`
- `tools/stage7_rewrite/scripts/build_weekly_activity_recommendation_pack.py`
- `tools/stage7_rewrite/scripts/build_weekly_activity_miniprogram_api.py`
- `tools/stage7_rewrite/scripts/run_stage8_write_strategy_tests.py`

