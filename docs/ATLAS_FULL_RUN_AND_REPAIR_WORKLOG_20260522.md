# Atlas Full Run And Repair Worklog

Updated: 2026-05-22 03:05 CST

Project: `C:\code\githubstar\wechathtmldownload`

## Scope

This worklog records the full Atlas execution chain from the public-safe serving build to the private full repair candidate.

Covered user intents:

- `/跑全量 跑生产`
- `/goal 想办法跑全量修复`
- `全量记录这次的工作日志`

Product target:

- China underground electronic music DJ relationship network.
- DJ / artist is the primary node.
- Events are historical performance facts.
- Venues, radio/media, labels/crews, organizers, source articles, public profiles, and future works/mixtapes are context and evidence.

Hard boundaries enforced:

- Do not mutate raw `atlas.sqlite`.
- Do not expose raw source URLs, raw HTML archive paths, raw JSON, or raw article UIDs in public serving schema.
- Do not deploy to Singapore VPS or CloudRun during this run.
- Do not read or print secrets, cookies, `.env`, tokens, or credentials.
- Do not run paid LLM/API processing.
- Do not write Neo4j/Qdrant/production external stores.
- Do not run broad `D:\` scans.
- Do not run destructive Git commands.

## Source Inputs

Raw/private inputs:

- Raw Atlas SQLite:
  `tools\stage7_rewrite\reports\atlas_local_sqlite_db_138102_20260521\atlas.sqlite`
- Low-cost repair sidecar:
  `reports\atlas_dj_low_cost_repair_sidecar_20260522\atlas_dj_low_cost_repair_sidecar.sqlite`
- Source URL recovery sidecar:
  `reports\atlas_source_url_recovery_20260522\atlas_source_url_recovery.sqlite`
- Event time normalized sidecar:
  `reports\atlas_event_time_normalized_sidecar_20260522\atlas_event_time_normalized_sidecar.sqlite`
- Curated public rules:
  `tools\stage7_rewrite\config\atlas_curated_entity_rules_20260522.json`

Previously recorded evidence:

- `docs\ATLAS_DJ_GRAPH_SAVEPOINT_AND_PLAN_20260522.md`
- `docs\ATLAS_HIGH_PERFORMANCE_DATABASE_ARCHITECTURE_20260522.md`
- `docs\ATLAS_SERVING_READ_MODEL_PRODUCTION_RUN_20260522.md`
- `docs\ATLAS_FULL_REPAIR_PRIVATE_CANDIDATE_20260522.md`

## Git And Workspace Safety

Repo path:

- `C:\code\githubstar\wechathtmldownload`

Branch:

- `feature/weekly-integrated-bridge`

The working tree was already heavily dirty with unrelated weekly-mini-program and historical untracked files. No cleanup, reset, checkout, or destructive command was run.

Backup snapshots created:

- `C:\code\.git-workspace-backups\wechathtmldownload\20260522-022413`
- `C:\code\.git-workspace-backups\wechathtmldownload\20260522-025237`
- `C:\code\.git-workspace-backups\wechathtmldownload\20260522-030519`

Latest backup summary:

- generated: `2026-05-22 03:05:22 +08:00`
- dirty entries: `2552`
- tracked changed: `22`
- untracked: `107348`
- copied untracked into backup: `200`
- skipped: `18`

## Implementation Work

### New Builder

Created:

- `tools\stage7_rewrite\scripts\build_atlas_serving_read_model.py`

Purpose:

- Build a separate public-safe or private-repair SQLite serving read model.
- Read raw/source DBs and sidecars in read-only mode.
- Materialize DJ-first tables for search, profiles, history, relations, venue/org rollups, evidence refs, and graph windows.

Key tables:

- `canonical_subject`
- `dj_profile`
- `performance_event`
- `dj_event`
- `dj_relation_rollup`
- `dj_venue_rollup`
- `dj_org_rollup`
- `evidence_ref`
- `search_document`
- `search_document_fts`
- `graph_window_cache`
- `build_metadata`

Search:

- SQLite FTS5 `trigram` tokenizer when available.
- No entity-type selector required.

Evidence boundary:

- `evidence_ref` stores `source_hash`, source account/title/date, and public-safe metadata.
- Raw source URL and archive HTML path are not copied.
- Public URL exposure defaults to `0`.

### New Test

Created:

- `tools\stage7_rewrite\tests\test_build_atlas_serving_read_model.py`

Covered cases:

- raw participants enter strict build;
- auto repaired participants/venue enter strict build;
- review-only participant rows stay out of strict build;
- `aggressive-private` includes review participant repairs;
- product/wine events are filtered even when they contain real DJ names;
- FTS search can find `MaFoL`;
- graph windows are created;
- no raw URL/archive path leaks into serving schema/content;
- `build_metadata.deployable_public` is `1` for strict and `0` for private repair.

Verification:

- `python -m py_compile tools\stage7_rewrite\scripts\build_atlas_serving_read_model.py`
- `python -m pytest tools\stage7_rewrite\tests\test_build_atlas_serving_read_model.py -q`
- result: `1 passed`

## Public Strict Build

### First Attempt

Command shape:

```powershell
python tools\stage7_rewrite\scripts\build_atlas_serving_read_model.py `
  --confirm-production-candidate RUN_ATLAS_SERVING_FULL `
  --graph-window-limit 0 `
  --force
```

Output:

- `reports\atlas_serving_read_model_20260522\atlas_serving.sqlite`

Initial result:

- raw events scanned: `608,678`
- performance events: `135,236`
- DJ profiles: `36,399`
- DJ-event edges: `339,319`
- directed DJ relation edges: `386,114`
- search documents: `191,716`
- graph windows: `36,399`
- duplicate event IDs skipped: `409,222`

Finding:

- Old event identity based on `source_uid#evid` collapsed a large number of local events.
- This created a false-fullness risk.

Fix:

- Public event IDs changed to a hashed stable ID using `source_article_uid + row_pk + evid + title/time/place`.
- This restores event uniqueness without exposing raw article UID.

### Second Attempt

Result after event-ID fix:

- raw events scanned: `608,678`
- performance events: `469,940`
- DJ profiles: `51,857`
- DJ-event edges: `1,109,635`
- directed DJ relation edges: `613,846`
- search documents: `549,939`
- graph windows: `51,857`
- duplicate event IDs skipped: `0`

Validation finding:

- Public search still contained `57` rows with wine/alcohol/menu terms.
- Examples included wine tasting, wine menu, and red-wine event titles/venue names.

Fix:

- Added event-level product/alcohol noise gate.
- Blocks wine/menu/product text before event materialization into DJ history, search, or graph windows.
- This catches cases where a real DJ name appears inside a non-music product promotion.

### Final Strict Public Candidate

Final output:

- `reports\atlas_serving_read_model_20260522\atlas_serving.sqlite`
- `reports\atlas_serving_read_model_20260522\manifest.json`
- `reports\atlas_serving_read_model_20260522\summary.md`

Final run:

- generated_at: `2026-05-22T02:43:40`
- elapsed: `222.72` seconds
- DB size: `1,803,362,304` bytes, about `1.72 GB`
- stderr: `0`

Final counts:

- raw events scanned: `608,678`
- performance events: `467,769`
- DJ profiles: `51,593`
- DJ-event edges: `1,104,301`
- directed DJ relation edges: `611,140`
- DJ-venue rollups: `103,231`
- DJ-org rollups: `296,365`
- venue subjects: `5,637`
- org/radio subjects: `22,375`
- evidence refs: `113,553`
- search documents: `547,374`
- graph windows: `51,593`
- product/noise events skipped: `4,267`
- duplicate event IDs skipped: `0`

Skipped / remaining participant gaps:

- missing: `12,072`
- not_ready: `37,952`
- review_only: `86,618`

Security checks:

- forbidden schema columns containing `source_url`, `archive_raw_html_path`, `raw_json`, or `article_uid`: `0`
- `evidence_ref.public_url_allowed != 0`: `0`
- public text hits for `mp.weixin`, `raw.html`, or `D:/`: `0`
- wine/alcohol/menu public search hits: `0`

Spot checks:

- `MaFoL`: search top result `dj / MaFoL`
- MaFoL strict profile: `149` events, `68` source refs, `18` venue rollups, `108` collaborators, `36` org rollups
- `DaRou`: search top result `dj / DaRou`
- `OIL`, `ALL`, `DADA`, `TAG`: searchable as venue/org surfaces
- `SHCR`, `BYYB`, `BAIHUI`, `CDCR`: radio/media subjects, not DJ profiles

Search latency spot check:

- min: `0.401 ms`
- p50: `1.163 ms`
- max: `42.303 ms`

Decision:

- This strict DB is the public deploy baseline.
- It still needs API/UI integration and anti-scrape gate verification before public deployment.

## Repair Candidate Mode Design

Problem:

- Strict public candidate leaves many `review_candidate` participant repairs out.
- Those rows are valuable for local recovery of DJ history, but too risky to publish blindly.

Decision:

- Add `--participant-acceptance` modes:
  - `strict`: public deploy candidate; raw participants + auto repairs only.
  - `balanced`: intermediate candidate; only high-confidence review participant repairs.
  - `aggressive-private`: maximal repair candidate; includes all ready review participant repairs after noise filters.

Safety:

- `strict` writes `build_metadata.deployable_public=1`.
- `balanced` and `aggressive-private` write `build_metadata.deployable_public=0`.
- Manifest marks `review_candidates_included=true` for private modes.

Review participant audit before implementation:

- review participant candidates: `81,298`
- confidence `0.7-0.8`: `38,630`
- confidence `0.6-0.7`: `34,626`
- confidence `0.5-0.6`: `7,292`
- confidence `0.4-0.5`: `750`
- all review candidate name lists were `<=16` names in the observed buckets
- a conservative safe-review rule would promote about `4,425` rows; aggressive-private promotes more but stays private.

## Full Private Repair Candidate

Command shape:

```powershell
python tools\stage7_rewrite\scripts\build_atlas_serving_read_model.py `
  --confirm-production-candidate RUN_ATLAS_SERVING_FULL `
  --graph-window-limit 0 `
  --force `
  --out-dir reports\atlas_serving_repair_full_private_20260522 `
  --participant-acceptance aggressive-private
```

Output:

- `reports\atlas_serving_repair_full_private_20260522\atlas_serving.sqlite`
- `reports\atlas_serving_repair_full_private_20260522\manifest.json`
- `reports\atlas_serving_repair_full_private_20260522\summary.md`

Final run:

- generated_at: `2026-05-22T02:56:26`
- elapsed: `248.042` seconds
- DB size: about `2.08 GB`
- stderr: `0`

Mode metadata:

- `participant_acceptance=aggressive-private`
- `deployable_public=0`
- `review_candidates_included=true`
- `raw_source_url_columns_copied=0`
- `archive_html_path_columns_copied=0`

Final counts:

- raw events scanned: `608,678`
- performance events: `538,034`
- DJ profiles: `55,791`
- DJ-event edges: `1,415,016`
- directed DJ relation edges: `772,998`
- DJ-venue rollups: `109,705`
- DJ-org rollups: `324,151`
- venue subjects: `6,067`
- org/radio subjects: `23,444`
- evidence refs: `115,963`
- search documents: `623,336`
- graph windows: `55,791`

Delta versus strict public candidate:

- performance events: `+70,265`
- DJ profiles: `+4,198`
- DJ-event edges: `+310,715`
- directed DJ relation edges: `+161,858`
- search documents: `+75,962`
- graph windows: `+4,198`

Participant repair contribution:

- auto participant repairs: `71,022`
- private review participant repairs: `70,265`
- remaining missing: `25,776`
- remaining not_ready: `37,952`
- remaining review_only: `2,649`
- product/noise events skipped: `4,267`

Security checks:

- forbidden schema columns containing `source_url`, `archive_raw_html_path`, `raw_json`, or `article_uid`: `0`
- `evidence_ref.public_url_allowed != 0`: `0`
- public text hits for `mp.weixin`, `raw.html`, or `D:/`: `0`
- wine/alcohol/menu search hits: `0`

Spot checks:

- MaFoL private profile: `196` events, `76` source refs, `19` venue rollups, `138` collaborators, `39` org rollups
- DaRou private profile: `84` events, `31` source refs, `10` venue rollups, `38` collaborators, `13` org rollups
- `SHCR`, `BYYB`, `BAIHUI`, `CDCR`: remain radio/media subjects, not DJ profiles

Search latency spot check:

- min: `0.452 ms`
- p50: `9.46 ms`
- max: `35.333 ms`

Decision:

- Private repair DB must not be deployed directly.
- It is the best current artifact for local review, quality scoring, and promotion-rule design.

## Documentation Updates

Created:

- `docs\ATLAS_SERVING_READ_MODEL_PRODUCTION_RUN_20260522.md`
- `docs\ATLAS_FULL_REPAIR_PRIVATE_CANDIDATE_20260522.md`
- `docs\ATLAS_FULL_RUN_AND_REPAIR_WORKLOG_20260522.md`

Updated:

- `docs\current-runtime.md`
- `docs\DOCUMENTATION_INDEX.md`
- `docs\ATLAS_DJ_GRAPH_SAVEPOINT_AND_PLAN_20260522.md`

Closeout command run:

```powershell
powershell -ExecutionPolicy Bypass -File C:\code\scripts\docs-neat-closeout.ps1
```

Result:

- generated project catalog and document inventory refreshed;
- MkDocs project sites rebuilt;
- existing warnings remain around historical HTML/Markdown conflicts and weekly plan anchors;
- no new Atlas build blocker from docs closeout.

## Known Risks

Strict public candidate risks:

- Still excludes many review participant candidates.
- Best public baseline today, but not the maximum data recovery.

Private repair candidate risks:

- Includes review participant repairs, so it may over-connect DJs from same-article evidence.
- Must stay private until sampled and promoted by rule.
- Larger relation graph can amplify false collaborations if review candidates are wrong.

Remaining data gaps:

- `25,776` missing participant rows after aggressive-private.
- `37,952` not-ready rows.
- `2,649` review-only rows after aggressive-private.
- Some venues still appear as address variants and need canonical merge later.
- Works/mixtapes/social profiles are not yet first-class serving tables in this build.

## Next Recommended Steps

1. Build a review dashboard or report over `aggressive-private` rows with the largest DJ/event/relation impact.
2. Sample by source account and venue to estimate false-positive rate.
3. Promote only safe classes into `balanced`, then rebuild a public candidate.
4. Wire local `/atlas/graph` APIs to the strict public DB first.
5. Verify the Chinese UI with one-box search, MaFoL, OIL, SHCR/BYYB, graph window pan/zoom/roam.
6. Deploy only strict or future balanced public DB behind Cloudflare Turnstile, WAF/rate limits, Nginx limits, app sessions, and no-bulk-export rules.

## Commands Verified In This Work Chain

```powershell
python -m py_compile tools\stage7_rewrite\scripts\build_atlas_serving_read_model.py
python -m pytest tools\stage7_rewrite\tests\test_build_atlas_serving_read_model.py -q
```

Full builds:

```powershell
python tools\stage7_rewrite\scripts\build_atlas_serving_read_model.py --confirm-production-candidate RUN_ATLAS_SERVING_FULL --graph-window-limit 0 --force
python tools\stage7_rewrite\scripts\build_atlas_serving_read_model.py --confirm-production-candidate RUN_ATLAS_SERVING_FULL --graph-window-limit 0 --force --out-dir reports\atlas_serving_repair_full_private_20260522 --participant-acceptance aggressive-private
```

Docs closeout:

```powershell
powershell -ExecutionPolicy Bypass -File C:\code\scripts\docs-neat-closeout.ps1
```

## Non-Actions

The following did not happen:

- no remote deployment;
- no CloudRun deployment;
- no mini-program upload/review;
- no raw source DB mutation;
- no paid LLM/API call;
- no network crawling;
- no Neo4j/Qdrant production write;
- no source URL or archive HTML publication;
- no secret/cookie/env-file read;
- no broad `D:\` scan;
- no destructive Git action.
