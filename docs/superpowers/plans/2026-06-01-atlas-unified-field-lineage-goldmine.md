# Atlas Unified Field Lineage Goldmine Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a read-only field alignment matrix and lineage audit that finds missing high-value Atlas fields before any E-drive unified database is materialized.

**Architecture:** Keep DB1, DB2, DB3, and sidecars separate as source layers. The first deliverable is a contract matrix plus report-only lineage/goldmine audit; only after those reports pass should a separate plan create `E:\workspace\projects\atlas\db\atlas_unified_v1`. The audit uses SQLite read-only connections, deterministic field mappings, stable row keys, count parity, field coverage, and blocked/candidate state labels.

**Tech Stack:** Python 3, SQLite read-only URI connections, JSON/JSONL/Markdown reports, existing `tools/stage7_rewrite` report conventions, optional later DuckDB/Parquet staging on E drive after approval.

---

## Status And Boundary

Status: `DESIGN_PLAN_READY_FOR_REVIEW`

This plan is intentionally report-only. It does not create an E-drive database, mutate DB1/DB2/DB3, fetch external pages, run LLM/OCR/provider calls, update public pointers, deploy CloudRun, upload the mini-program, write Neo4j/Qdrant/mem0/agentmemory, or read secrets.

Current authority layers verified on 2026-06-01:

- DB1 source/raw Atlas: `C:\code\githubstar\wechathtmldownload\reports\atlas_incremental_wechat_refresh_20260522_1438\atlas_local_sqlite_db_139123_activity_candidate_current_20260525_1435\atlas.sqlite`
  - Size: about `3843 MB`
  - Core counts: `articles=139123`, `events=609235`, `entities=1515202`, `atlas_activity_events=196`, `atlas_activity_evidence_refs=2181`
- DB2 current serving read model: `C:\code\githubstar\wechathtmldownload\reports\atlas_serving_time_overlay_span_split_search_date_refresh_candidate_20260527_2018\atlas_serving.sqlite`
  - Size: about `2088 MB`
  - Core counts: `canonical_subject=82878`, `performance_event=508049`, `dj_profile=53555`, `dj_event=1285827`, `dj_relation_rollup=701396`, `dj_venue_rollup=137101`, `dj_org_rollup=323335`, `evidence_ref=130591`, `search_document=590927`, `graph_window_cache=53555`
- DB2 final-family candidate: `C:\code\githubstar\wechathtmldownload\reports\atlas_serving_final_20260528\atlas_serving.sqlite`
  - Lower row counts than current DB2; must not replace DB2 blindly.
- DB3 mini-program projection: `C:\code\githubstar\wechathtmldownload\services\weekly_activity_cloudrun\data\atlas_miniapp.sqlite`
  - Size: about `350 MB`
  - Core counts: `subject=82782`, `dj_profile=53459`, `dj_event=899497`, `dj_collaborator=183163`, `dj_venue=137101`, `source_ref=118940`
- T6 social overlay: `C:\code\githubstar\wechathtmldownload\tools\stage7_rewrite\reports\atlas_t6_sidecar_new_db_overlay_t5_t6_20260526\atlas_t6_sidecar_social_overlay.sqlite`
  - Core counts: `atlas_dj_social_links=18710`, `atlas_dj_social_entity_rollups=1975`
- Companion/outlink DB: `C:\code\githubstar\wechathtmldownload\tools\stage7_rewrite\reports\atlas_dj_companion_20260522\atlas_dj_v2.sqlite`
  - Core counts: `dj_entities=79605`, `dj_social_profiles=30423`, `dj_outlinks=18702`, `dj_identity_candidates=4768`, `dj_mixtapes=755`, `dj_youtube_channels=2396`, `dj_youtube_videos=8464`, `dj_sc_stats=651`
- S119 external-link sidecar: `C:\code\githubstar\wechathtmldownload\tools\stage7_rewrite\reports\external_link_db2_sidecar_contract_s119_20260601\external_link_db2_sidecar.sqlite`
  - Core counts: `external_link_candidates=748`, high confidence `56`, blocked `36`, `db2_projection_allowed=0`

Known blockers that must stay visible:

- Relation identity/write gate: `2045` blockers, with `db3_profile_empty_normalized_name=33` and `db3_same_normalized_name_multi_id=2012`.
- T6 year-context review: `1366` rows blocked; `443` need source artifacts.
- Weekly current package gaps: `source_ref_or_hash=0`, `external_music_links=0`, geo `207/208`.
- External links and DJ Interview submissions remain candidate/private sidecar data until consent/source/review gates pass.

## Field Alignment Matrix

This matrix is the target contract for the first audit. It describes where each public or future-public field comes from, which layer owns it, and what state it may reach.

| Family | Unified field | DB1 source/raw input | DB2 serving input | DB3 miniapp input | Sidecar/candidate input | State rule |
| --- | --- | --- | --- | --- | --- | --- |
| identity | `subject_id` | `entities.eid`, `events.evid` for event-only subjects | `canonical_subject.subject_id`, `dj_profile.dj_id` | `subject.subject_id`, `dj_profile.dj_id` | `dj_identity_candidates.subject_id`, `external_link_candidates.entity_search_id` | DB2 id wins for public facts; sidecar ids stay candidate. |
| identity | `subject_type` | `entities.type`, `source_kind` hints | `canonical_subject.subject_type` | `subject.subject_type` | `entity_type`, `entity_kind`, public category | Normalize to `dj`, `venue`, `organizer`, `radio`, `event`, `external_link`. |
| identity | `display_name` | `entities.name`, `events.name` | `canonical_subject.display_name`, `dj_profile.display_name` | `subject.display_name`, `dj_profile.display_name` | `entity_name`, `display_name`, `handle` | Non-empty DB2 public value wins; sidecar display values need review label. |
| identity | `normalized_name` | derived from `entities.name` | `canonical_subject.normalized_name`, `dj_profile.normalized_name` | `subject.normalized_name`, `dj_profile.normalized_name` | `normalized_name`, normalized handle | Empty DB3 normalized names are blockers, never public_fact. |
| identity | `aliases_json` | `entities.aliases_json` | `canonical_subject.aliases_json`, `dj_profile.aliases_json` | `subject.aliases_json`, `dj_profile.aliases_json` | profile handles, social aliases | Preserve non-empty aliases; record alias provenance. |
| identity | `city_primary` | `entities.city`, `events.city`, `articles.city_label` | `canonical_subject.city_primary`, `dj_profile.city_primary`, event city rollups | `subject.city_primary`, `dj_profile.city_primary` | profile city hints | City-scoped join wins before name-only join. |
| identity | `confidence` | `entities.confidence`, `events.confidence` | `canonical_subject.confidence`, `dj_profile.confidence` | `dj_event.confidence` | sidecar confidence score/band | Do not mix score systems without `confidence_source`. |
| event | `event_id` | `events.evid`, `atlas_activity_events.event_id` | `performance_event.event_id`, `dj_event.event_id` | `dj_event.event_id` | external source refs only | DB2 event id is serving id; DB1 event id stays lineage input. |
| event | `event_title` | `events.name`, `atlas_activity_events.title` | `performance_event.event_title`, `dj_event.event_title` | `dj_event.event_title` | source title only | Prefer DB2 title for public; use DB1 to find missing/weak titles. |
| event | `starts_at` | `events.time_iso`, activity `event_date_start`, `time_start` | `performance_event.starts_at`, `dj_event.starts_at` | `dj_event.starts_at` | source artifact date evidence | Missing/ambiguous dates become goldmine candidates, not direct writes. |
| event | `time_text` | `events.time_text`, activity `event_time_text` | `performance_event.time_text`, `dj_event.time_text` | absent or reduced | source snippets | Preserve original text as evidence; do not overwrite ISO with text. |
| event | `venue_id` | activity `venue_id`, `events.place` as weak input | `performance_event.venue_id`, `dj_event.venue_id`, `dj_venue_rollup.venue_id` | `dj_event.venue_id`, `dj_venue.venue_id` | profile venue references | Use city-scoped venue key; Loopy/OIL style fragmentation must queue review. |
| event | `venue_name` | `events.place`, activity `venue_name` | `performance_event.venue_name`, `dj_event.venue_name`, `dj_venue_rollup.venue_name` | `dj_event.venue_name`, `dj_venue.venue_name` | source/profile mentions | Preserve aliases separately; do not collapse venue/org homonyms without evidence. |
| event | `city` | `events.city`, activity `city_key`, `city_name` | `performance_event.city`, `dj_event.city` | `dj_event.city`, `dj_venue.city` | profile hints | DB2 public city wins; DB1 can repair missing DB2 city through gated audit. |
| relation | `dj_event` | `events.participants_json`, `entities` mentions | `dj_event` | `dj_event` | source/profile sidecars | DB2 is relation truth; DB3 may be reduced by projection. |
| relation | `same_event_count` | derived from DB1 event participants | `dj_relation_rollup.same_event_count` | `dj_collaborator.same_event_count` | none | DB2 count is canonical for public relation; use DB1 to explain gaps. |
| relation | `relation_score` | derived only | `dj_relation_rollup.relation_score` | `dj_collaborator.relation_score` | candidate match score is separate | Never combine relation score and identity match confidence. |
| relation | `sample_evidence_json` | source event rows | `dj_relation_rollup.sample_evidence_json`, `dj_org_rollup.sample_evidence_json` | absent | sidecar evidence text | This is a goldmine field for evidence drawers when snippets are empty. |
| relation | `venue_event_count` | derived from events/place | `dj_venue_rollup.event_count` | `dj_venue.event_count` | none | Preserve even if weekly current has empty venue arrays. |
| evidence | `source_ref_id` | `source_article_uid`, activity source refs | `evidence_ref.source_ref_id`, event `source_ref_id`, activity evidence refs | `source_ref.source_ref_id`, `dj_event.source_ref_id` | `source_ref`, interview `sourceRefId` | Primary evidence lookup key; `sourceHash` is not a substitute. |
| evidence | `source_hash` | activity `source_url_hash`, article hash inputs | `evidence_ref.source_hash`, `activity_event_detail.source_hash` | `source_ref.source_hash` | URL hash, cache key | Useful for privacy-safe routing; not sufficient for evidence lookup. |
| evidence | `source_account` | `articles.source_account`, activity `source_account_name` | `evidence_ref.source_account`, `activity_event_detail.source_account_name` | `source_ref.source_account` | profile/source layer | Public-safe metadata if no raw URL/path leaks. |
| evidence | `source_title` | `articles.title`, activity source title | `evidence_ref.source_title` | `source_ref.source_title` | source title | Good display field; raw article body remains private. |
| evidence | `public_snippet` | `entities.evidence_quote`, activity `quote` | `evidence_ref.public_snippet`, `activity_evidence_ref.quote` | absent | evidence text candidate | Empty snippets are not blockers if structured event evidence exists. |
| evidence | `public_url_allowed` | should stay private by default | `evidence_ref.public_url_allowed` | absent | candidate URL category | Must remain `0` unless a public jump endpoint gate passes. |
| external | `external_link_id` | none | none in DB2 core | none in DB3 core | `external_link_candidates.sidecar_id`, `dj_outlinks.outlink_id`, `atlas_dj_social_links.candidate_id` | Candidate id only; not public identity. |
| external | `platform` | none | none | none | `platform`, `outlink_platform`, social link platform | Allowed as candidate metadata. |
| external | `url` | raw source URLs must not leak | none | none | candidate URL, profile URL, canonical URL key hash | Public surface should expose only jump-out URLs after copyright/privacy gate. |
| external | `copyright_safety` | none | none | none | S119 `copyright_safety`, block reasons | Direct media/archive links remain blocked. |
| external | `db2_projection_allowed` | none | none | none | S119 `db2_projection_allowed`, overlay public flags | Must be `true` before any DB2 projection; currently `0`. |
| media | `avatar_asset_id` | source artifacts only | `dj_profile.avatar_asset_id` currently empty | `dj_profile.avatar_url` exists but may be candidate | avatar sidecars, identity candidates | Public avatar requires binary provenance, checksum, and binding gate. |
| miniapp | `mobile_display_name` | none | source from DB2 selected fields | `subject.display_name`, `dj_profile.display_name` | candidate labels hidden by default | DB3 is projection, not authority. |
| audit | `fact_state` | source row state | DB2 public state | DB3 projected state | candidate/review/report state | Required values: `public_fact`, `candidate`, `report_only`, `review_ready`, `blocked`, `production_effective`. |
| audit | `lineage_run_id` | generated manifest hash | generated manifest hash | generated manifest hash | generated manifest hash | Every output row in reports must include lineage. |

## Goldmine And Missing-Field Audit Targets

The audit should look for fields that already exist in one layer but are missing, reduced, or unsafe in another layer.

1. DB1 event goldmine
   - Compare DB1 `events=609235` with DB2 `performance_event=508049`.
   - Group DB1-only events by `source_kind`, `confidence`, `time_iso`, `city`, `place`, `source_article_uid`.
   - Identify high-confidence DB1 events with non-empty `time_iso`, `city`, and `participants_json` that did not become DB2 serving events.
   - Output `db1_event_not_in_db2_candidates.jsonl`.

2. DB2 to DB3 projection loss
   - Compare `dj_event` DB2 `1285827` vs DB3 `899497`.
   - Compare `dj_relation_rollup` DB2 `701396` vs DB3 `dj_collaborator=183163`.
   - Compare `evidence_ref` DB2 `130591` vs DB3 `source_ref=118940`.
   - Flag missing DB3 source refs referenced by DB3 `dj_event`.
   - Output `db2_to_db3_projection_loss.json`.

3. Identity blockers
   - Preserve existing blockers: `db3_profile_empty_normalized_name=33`, `db3_same_normalized_name_multi_id=2012`.
   - Rank blockers by `event_count`, `relation_count`, `source_ref` presence, and sidecar evidence availability.
   - Do not auto-merge identities.
   - Output `identity_blocker_goldmine_ranked.jsonl`.

4. Evidence drawer goldmine
   - Count empty `evidence_ref.public_snippet`.
   - Extract candidate structured evidence from `dj_relation_rollup.sample_evidence_json` and `dj_org_rollup.sample_evidence_json`.
   - Join to `source_ref_id` and report which relation/profile pages can show event-table evidence even without snippets.
   - Output `structured_evidence_drawer_candidates.jsonl`.

5. Venue alias goldmine
   - Detect fragmented venues such as Loopy-style same name/different city and OIL-style venue/org dual identity.
   - Use `canonical_subject`, `dj_venue_rollup`, `performance_event`, and DB1 `events.place`.
   - Output `venue_alias_lineage_candidates.jsonl`.

6. External link goldmine
   - Reconcile S119 `external_link_candidates=748`, T6 overlay `atlas_dj_social_links=18710`, companion `dj_outlinks=18702`, and `dj_identity_candidates=4768`.
   - Find high-confidence links that have matching DB2 `dj_profile` or DB3 `dj_profile` but still have `db2_projection_allowed=0`.
   - Keep all rows as `candidate` or `blocked`.
   - Output `external_link_projection_candidates.jsonl`.

7. Weekly current field gaps
   - Reuse current facts: weekly current `208` items, source refs `0`, external music links `0`, geo `207/208`.
   - Locate matching DB1/DB2/DB3 fields that could fill these gaps under non-empty preservation.
   - Output `weekly_current_missing_field_goldmine.jsonl`.

8. Avatar/media goldmine
   - Report DB2 `dj_profile.avatar_asset_id` and `media_count` coverage.
   - Join only redacted/hashed sidecar rows; do not expose raw paths or raw media URLs.
   - Output `avatar_media_candidate_coverage.json`.

## Historical Intake Findings From Shallow Scan

These findings come from a bounded 2026-06-01 shallow scan. They refine the slow-scan plan but do not authorize recursive scanning or DB promotion.

- WSL DeepSeekTUI runtime:
  - Root: `\\wsl.localhost\Ubuntu\home\pc\.deepseek`
  - Recent sessions/logs exist through 2026-06-01.
  - `tasks/queue.json` currently has `queue_len=0`.
  - Memory note to preserve: stale `running` task JSON is not enough; combine log tails, `ps`, queue/runtime state, and artifact counts.
  - Search hits for `Atlas`, `DB2`, `outlink`, `avatar`, `DDownload`, `rawwechat`, and `DJ_DATA` exist across sessions/memory/logs, but full session JSON files must be indexed slowly and summarized before use.
  - 2026-06-01 WSL readback found `tasks/tasks` recent sample status counts `completed=63`, `canceled=16`, `failed=1`; many titles are repeated `Atlas 守夜人长跑` or `Atlas Marathon Engine` status checks. These are job-control history, not evidence of DB quality by themselves.
  - `state/subagents.v1.json` has `4` subagents, all marked `Completed`, covering discovery workers, deep-crawl workers, browser-intensive workers, and autonomous monitor/autopilot components. Treat these as orchestration completion only; verify side effects in DB/artifact files.
  - Logs repeatedly show `path_escape` when DeepSeek tried to read `/mnt/c/code/githubstar/wechathtmldownload/tools/stage7_rewrite/reports/atlas_marathon_20260525/marathon_summary.json`, `marathon_checkpoint.json`, and other Windows-side files. Any old DeepSeek conclusion about those files must be rechecked from the Windows repo path.
  - `.deepseek/memory/*.jsonl` can contain sensitive configuration snippets inside `confirmed_facts`. The history indexer must whitelist metadata fields and must not grep or export raw memory records.
- T6 DeepSeekTUI outlink/avatar memory:
  - Older candidate chain had `accepted_for_graph=0`, `avatar_display_allowed=0`, and `public_serving_field_allowed=0`.
  - Old mailroom/adapter state must stay `draft-only` unless revalidated.
  - Repo-local escaped `D\DJ_DATA` artifacts are not equivalent to real `D:\DJ_DATA` or moved `D:\DJ_DATA.moved-to-E-20260528` paths.
- D-drive source artifact roots:
  - `D:\DDownload` first-level shallow scan found `255` entries. This root contains useful Atlas/Stage7 article-release roots and also many secret-looking/cookie/key files. Secret-looking files are excluded from all downstream scans and must not be opened by default.
  - Confirmed DDownload child roots:
    - `D:\DDownload\_queues`
    - `D:\DDownload\_archive_mptext`
    - `D:\DDownload\_llm_artifacts`
    - `D:\DDownload\_llm_release`
    - `D:\DDownload\_llm_release_v2`
    - `D:\DDownload\_llm_md`
    - `D:\DDownload\_reports`
  - `D:\DDownload\.wechat-live-stage-lock.json` is absent on the 2026-06-01 readback.
  - `D:\DDownload\_llm_artifacts\export-llm-status.json`: `status=completed`, `totalItems=93761`, `succeededCount=93508`, `failedCount=253`, `completedCount=93761`, `startedAt=2026-04-23T21:26:52.012Z`, `endedAt=2026-04-25T13:06:32.388Z`.
  - `D:\DDownload\_archive_mptext\mptext-archive-status.json`: `totalItems=93761`, `succeededCount=66020`, `failedCount=7243`, `skippedCount=17874`, `deferredCount=2624`.
  - `D:\DDownload\_archive_mptext\asset-retention-status.json`: `totalItems=117`, `succeededCount=113`, `failedCount=4`.
  - `D:\DDownload\_queues\download_ready_queue.jsonl` exists and contains source metadata such as account key, fakeid, token, source URL, title, post time, post date, discovery source, and status. It must be read by line/metadata only, not copied wholesale.
  - `D:\DDownload\_llm_release_v2\manifest.json`: `total_articles=93000`, `copied_articles=93000`, quality counts `ready=81425`, `review=10437`, `blocked=1138`.
  - `D:\DDownload\_llm_release_v2\index.jsonl`: `93000` rows, `63` account directories, top accounts include `TAGChengdu=6227`, `VERVO国际独立电音俱乐部=5711`, `Dada Bar Beijing=5070`, `OIL油=4928`, `All俱乐部=4374`, `Elevator上海=4165`.
  - `D:\DDownload\_llm_release_v2\index.jsonl` currently has `post_date` empty on all `93000` rows, but this is a projection loss rather than source loss: a bounded stream join back to `D:\DDownload\_queues\download_ready_queue.jsonl` on `(account, token)` matches all `93000` release rows, and all matched queue rows have date metadata.
  - `D:\DDownload\_queues\download_ready_queue.jsonl` has `93761` rows and `93253` unique `(account, token)` keys. The release contains `93000` of those keys; the `253` unique queue keys not in release align with export failures and must be kept as a failed-source queue, not silently merged.
  - Queue duplicate handling is required: `4` duplicate `(account, token)` keys account for `508` extra queue rows. Any date-repair job must choose a deterministic source row and emit a duplicate-key audit file.
  - Sampled `D:\DDownload\_llm_release_v2\articles\<account>\<token>` directories contain `llm_input.md`, `sidecar.json`, `quality_report.json`, `meta.json`, `assets.json`, and `poster_ocr.json`.
  - `D:\DDownload\_llm_release_v2` is a stronger source-artifact layer than the old generic DeepSeek release pack because it preserves sidecar provenance, poster OCR, local asset metadata, quality reports, and the clean release manifest while excluding raw HTML/MHTML/PDF/URL files.
  - `D:\rawwechat_archive_mptext` contains `mptext-archive-status.json`, `dajiala-repair-status.json`, and `asset-retention-status.json`.
  - `mptext-archive-status.json`: total `6228`, succeeded `0`, failed `1057`, skipped `5171`.
  - `dajiala-repair-status.json`: total `1057`, succeeded `0`, failed `1057`, with deleted/unavailable article messages.
  - `asset-retention-status.json`: total `6228`, skipped `6228` because existing `assets_local.json` was present.
  - `D:\rawwechat_md_smoke` has one MarkItDown smoke success from one HTML input.
- Legacy Stage7 evidence:
  - `D:\STAGE7_FINAL_EVIDENCE_PACK_2026-04-28_0847` exists with `00_INDEX`, `12_HANDOFF`, and manifest files.
  - Final summary status is `AMBER`, with about `3236/93000` processed JSON files and Stage 8 dry-run not executed at that time.
  - Treat this as historical extraction evidence, not current Atlas serving truth.
- DJ_DATA moved root:
  - `D:\DJ_DATA.moved-to-E-20260528` exists with `swarm`, `databases`, `avatars`, `radio_crawl`, `archives`, `reports`, `processed`, `raw`, `logs`, and `models`.
  - `databases\atlas_avatars.sqlite` exists.
  - Read-only counts: `avatars=2956`, `avatar_download_log=4731`.
  - Columns include `file_path`, `sha256`, `accepted_for_graph`, and `graph_write_allowed`; public promotion still requires redaction/provenance gates.

## Slow Scan Source Registry

The slow scan is a manifest-first discovery pass. It must not recursively scan D-drive roots. Each source gets a stable registry row with path, authority level, expected artifact types, allowed scan depth, and promotion boundary.

| Source path | Exists 2026-06-01 | Authority level | First scan mode | Goldmine target | Hard boundary |
| --- | --- | --- | --- | --- | --- |
| `C:\code\githubstar` | yes | code/source registry | repo-local `rg --files`, limited to project names and manifests | sibling repos, old tools, local open-source helpers | no cross-repo mutation |
| `C:\code` | yes | ops/docs registry | known docs/scripts only | module logs, ops handoffs, old Stage7 evidence refs | no broad recursive scan |
| `C:\Users\pc\code\dj-dataset` | yes, symlink | dataset pointer | resolve target, list root only | DJ source dataset lineage | do not follow blindly until target is recorded |
| `C:\Users\pc\code\huaidj-submit` | yes | app/tool repo | repo status + manifest files | submit pipeline fields, external submission schema | no deployment |
| `D:\DDownload` | yes | cold-data root | no root scan; only known child paths from docs/manifests | `_llm_release_v2`, historical 93k indices | root recursion banned |
| `D:\rawwechat_archive_mptext` | yes | source artifact cache | status JSON first, then failed/succeeded token samples | failed mptext/dajiala source recovery candidates | no paid/API retry |
| `D:\weixinoutput` | yes | output/manual packs | root shallow list, then selected Loopy/Atlas dirs | old Loopy/manual OCR/source evidence | no bulk read |
| `D:\HTML_retry_rate_limited` | yes | failed HTML URL hints | root files only | rate-limited URL retry candidates | no fetch |
| `D:\rawwechat_md_smoke_input` | yes | smoke input | known single HTML sample | HTML-to-MD parser validation | no broad HTML scan |
| `D:\rawwechat_md_smoke` | yes | smoke output | status JSON + generated MD | MarkItDown quality baseline | no overwrite |
| `D:\rawwechat` | yes | large source root | no root recursion; sample by manifest only | raw article/HTML goldmine | root recursion avoided |
| `D:\rawwechat_discovery` | yes | discovery queues | root shallow list, known queues | TAGChengdu history and partial probes | no network retry |
| `D:\rawwechat_md` | yes | large markdown root | no root recursion; manifest/sample only | article text goldmine | no full-text global grep |
| `D:\HTML` | yes | large HTML root | no root recursion; manifest/sample only | raw HTML/source artifact candidates | no full HTML crawl |
| `D:\STAGE7_FINAL_EVIDENCE_PACK_2026-04-28_0847` | yes | historical evidence pack | `00_INDEX` and `12_HANDOFF` first | old Stage7 run state and failure modes | historical only |
| `D:\graph_candidates` | yes | graph candidate artifacts | shallow child dirs | dry-run graph candidate schema | no Neo4j/Qdrant write |
| `D:\artifacts` | yes | canary artifacts | shallow child dirs | Stage7 v1 canary evidence | no promotion |
| `D:\DJ_DATA.moved-to-E-20260528` | yes | moved DJ data sidecar | shallow dirs + selected SQLite schema/count | avatar/social/radio goldmine | no raw media publication |

## Slow Scan Output Shape

Every slow-scan run must write report-only artifacts under:

`tools/stage7_rewrite/reports/atlas_goldmine_slow_scan_YYYYMMDD/`

Required outputs:

- `source_registry.json`: one row per source root or known child artifact.
- `source_registry.md`: human summary with risk tier and next allowed scan.
- `deepseek_history_index.jsonl`: WSL DeepSeek session/memory/log hits, one row per matching file, with size/mtime/keyword counts only.
- `d_drive_manifest_index.jsonl`: D-drive shallow/manifest rows, no raw article bodies.
- `artifact_goldmine_candidates.jsonl`: candidate rows with `candidate_state`, `source_path`, `source_kind`, `field_family`, `why_interesting`, `next_gate`.
- `scan_safety.json`: confirms no root recursion, no network, no secrets, no DB writes, no media publication.

Candidate states:

- `index_only`: path or manifest exists, content not inspected.
- `sample_ready`: small safe sample can be read next.
- `candidate`: field appears valuable but not accepted.
- `blocked`: missing provenance, private path/url, identity ambiguity, or unsafe media.
- `historical_only`: useful for context but superseded by current DB/SSOT.

## Added Slow-Scan Tasks

These tasks extend the first plan. They refine discovery before any DB materialization.

### Task 7: WSL DeepSeek History Index

**Files:**
- Create: `tools/stage7_rewrite/scripts/build_wsl_deepseek_history_index.py`
- Create: `tools/stage7_rewrite/tests/test_build_wsl_deepseek_history_index.py`

- [ ] **Step 1: Write fixture test**

```python
def test_deepseek_index_records_keyword_hits_without_session_body(tmp_path):
    root = tmp_path / ".deepseek"
    (root / "sessions").mkdir(parents=True)
    session = root / "sessions" / "s1.json"
    session.write_text('{"text":"Atlas DB2 outlink avatar lineage"}', encoding="utf-8")
    report = build_index(root, keywords=["Atlas", "DB2", "outlink"], out_dir=tmp_path / "out")
    assert report["summary"]["matching_files"] == 1
    row = report["rows"][0]
    assert row["path"].endswith("s1.json")
    assert row["keyword_hits"]["Atlas"] == 1
    assert "text" not in row
```

- [ ] **Step 2: Implement metadata-only indexing**

The script must only record:

- path
- size
- mtime
- file kind: `session`, `memory`, `log`, `queue`, `state`
- keyword hit counts
- task status counts from `tasks/tasks/*.json` without task body expansion
- subagent status counts from `state/subagents.v1.json`
- repeated runtime error categories such as `path_escape`
- first 200-character redacted snippet only when `--include-snippet` is explicitly set

Default command:

```powershell
python tools\stage7_rewrite\scripts\build_wsl_deepseek_history_index.py --wsl-root "\\wsl.localhost\Ubuntu\home\pc\.deepseek" --out-dir tools\stage7_rewrite\reports\atlas_goldmine_slow_scan_20260601
```

Expected safety:

```text
session_bodies_copied=false
raw_memory_records_exported=false
confirmed_facts_exported=false
secrets_read=false
queue_len_recorded=true
```

Current WSL readback facts that the script should reproduce:

```text
deepseek_root=\\wsl.localhost\Ubuntu\home\pc\.deepseek
task_sample_completed=63
task_sample_canceled=16
task_sample_failed=1
subagents_total=4
subagents_completed=4
path_escape_hits_include=atlas_marathon_20260525/marathon_summary.json
```

### Task 8: D-Drive Source Registry

**Files:**
- Create: `tools/stage7_rewrite/scripts/build_atlas_goldmine_source_registry.py`
- Create: `tools/stage7_rewrite/tests/test_build_atlas_goldmine_source_registry.py`

- [ ] **Step 1: Write path-policy test**

```python
def test_registry_marks_large_roots_manifest_only(tmp_path):
    paths = [r"D:\DDownload", r"D:\rawwechat", r"D:\rawwechat_md", r"D:\HTML", r"D:\rawwechat_archive_mptext"]
    report = build_registry(paths)
    by_path = {row["path"]: row for row in report["sources"]}
    assert by_path[r"D:\DDownload"]["scan_policy"] == "known_child_only"
    assert by_path[r"D:\rawwechat_archive_mptext"]["scan_policy"] == "manifest_first"
    assert report["safety"]["d_root_recursive_scan"] is False
```

- [ ] **Step 2: Implement registry builder**

The script must:

- call `Get-Item` equivalent only for path existence and mtime
- list at most first-level children for bounded paths
- never recurse into `D:\DDownload`, `D:\rawwechat`, `D:\rawwechat_md`, or `D:\HTML`
- prefer known status JSON files over broad file search

Default source list must include exactly the user-provided roots from this plan.

### Task 9: Raw WeChat Artifact Goldmine

**Files:**
- Create: `tools/stage7_rewrite/scripts/audit_rawwechat_artifact_goldmine.py`
- Create: `tools/stage7_rewrite/tests/test_audit_rawwechat_artifact_goldmine.py`

- [ ] **Step 1: Test mptext/dajiala status parsing**

```python
def test_rawwechat_goldmine_extracts_failed_and_skipped_counts(tmp_path):
    status = tmp_path / "mptext-archive-status.json"
    status.write_text(json.dumps({"totalItems": 3, "succeededCount": 1, "failedCount": 1, "skippedCount": 1, "items": []}), encoding="utf-8")
    report = audit_status_files([status], out_dir=tmp_path / "out")
    assert report["summary"]["total_items"] == 3
    assert report["summary"]["failed_items"] == 1
    assert report["safety"]["network_fetch_executed"] is False
```

- [ ] **Step 2: Implement status-only audit**

Initial real input files:

- `D:\rawwechat_archive_mptext\mptext-archive-status.json`
- `D:\rawwechat_archive_mptext\dajiala-repair-status.json`
- `D:\rawwechat_archive_mptext\asset-retention-status.json`
- `D:\rawwechat_md_smoke\markitdown-batch-status.json`

Output:

- `rawwechat_artifact_goldmine_summary.json`
- `rawwechat_failed_source_candidates.jsonl`
- `rawwechat_smoke_quality_rows.jsonl`

No retry/fetch is allowed in this task.

### Task 10: Legacy Stage7 Evidence Pack Index

**Files:**
- Create: `tools/stage7_rewrite/scripts/index_legacy_stage7_evidence_pack.py`
- Create: `tools/stage7_rewrite/tests/test_index_legacy_stage7_evidence_pack.py`

- [ ] **Step 1: Test evidence pack state classification**

```python
def test_stage7_pack_amber_is_historical_only(tmp_path):
    summary = tmp_path / "FINAL_SUMMARY.md"
    summary.write_text("# FINAL SUMMARY\n\n**Status**: AMBER\n- Processed JSON files: 3,236\n", encoding="utf-8")
    report = index_pack(summary.parent, out_dir=tmp_path / "out")
    assert report["decision"] == "legacy_stage7_evidence_pack_indexed_historical_only"
    assert report["state"] == "historical_only"
```

- [ ] **Step 2: Implement indexer**

Real source:

`D:\STAGE7_FINAL_EVIDENCE_PACK_2026-04-28_0847`

The indexer reads only:

- `00_INDEX\FINAL_SUMMARY.md`
- `00_INDEX\MANIFEST.json`
- `00_INDEX\SHA256SUMS.txt`
- `12_HANDOFF\HANDOFF_FOR_CHATGPT.md`

It must not read all log tails or raw outputs by default.

### Task 11: DJ_DATA Moved Avatar Goldmine

**Files:**
- Create: `tools/stage7_rewrite/scripts/audit_dj_data_moved_avatar_goldmine.py`
- Create: `tools/stage7_rewrite/tests/test_audit_dj_data_moved_avatar_goldmine.py`

- [ ] **Step 1: Test avatar DB gate classification**

```python
def test_avatar_rows_stay_candidate_until_graph_flags_pass(tmp_path):
    db = tmp_path / "atlas_avatars.sqlite"
    create_avatar_db(db, accepted_for_graph=0, graph_write_allowed=0)
    report = audit_avatar_db(db, out_dir=tmp_path / "out")
    assert report["summary"]["avatars"] == 1
    assert report["summary"]["public_allowed"] == 0
    assert report["rows"][0]["candidate_state"] == "candidate"
```

- [ ] **Step 2: Implement read-only avatar schema/count audit**

Real source:

`D:\DJ_DATA.moved-to-E-20260528\databases\atlas_avatars.sqlite`

Required report:

- `avatar_goldmine_summary.json`
- counts for `avatars` and `avatar_download_log`
- coverage for `sha256`, `width`, `height`, `content_type`
- counts for `accepted_for_graph=1` and `graph_write_allowed=1`
- leak scan for raw `file_path` exposure in generated reports

No image read, copy, thumbnail generation, upload, or public field write is allowed.

### Task 12: Consolidated Goldmine Decision

**Files:**
- Create after Tasks 7-11: `reports/ATLAS_GOLDMINE_SLOW_SCAN_DECISION_20260601.md`

- [ ] **Step 1: Combine report-only findings**

The decision report must rank goldmine sources by:

1. Missing public-safe fields with strong lineage.
2. Missing DB2 fields already present in DB1/source artifacts.
3. Missing DB3 projection fields already safe in DB2.
4. Candidate sidecar fields that need human/source/copyright gates.
5. Historical-only evidence that should not affect current DB design.

- [ ] **Step 2: Reopen E-drive DB build only after decision**

The E-drive build remains blocked until the consolidated decision names:

- which fields enter staging,
- which fields remain sidecar-only,
- which paths are excluded,
- which scans are still needed,
- and which gates must pass before DB materialization.

## DeepSeek Legacy Extraction Quality Readback

This readback was added after checking the older DeepSeek superlongrun release packs, later repair reports, and current DB projections. It changes the pipeline design assumptions: the old DeepSeek path is useful source evidence, but it is not a lossless activity or profile database.

Verified old release-pack facts:

- `consumer_release_pack_all_deepseek_127490_20260519`:
  - `articles=127490`, `events=589320`, `entities=1456290`
  - `missing_publish_time_articles=127490`
  - `decision=staging_ready_with_unknown_publish_time`
- `consumer_release_pack_all_deepseek_127511_20260520`:
  - `articles=127511`, `events=589365`, `entities=1456325`
  - `missing_publish_time_articles=127511`
  - `decision=staging_ready_with_unknown_publish_time`
- Streamed field coverage from `consumer_release_pack_all_deepseek_127511_20260520`:
  - `articles.publish_time`: `0/127511`
  - `articles.city_label`: `0/127511`
  - `events.time_iso`: `0/589365`
  - `events.city`: `0/589365`
  - `events.time_text`: `561875/589365` (`95.34%`)
  - `events.place`: `452085/589365` (`76.71%`)
  - `events.participants`: `390176/589365` (`66.20%`)
  - `events.organizers`: `352187/589365` (`59.76%`)
  - `entities.name` and `entities.type`: `100%`
  - `entities.city`: `0/1456325`
  - `entities.bio`: `986907/1456325` (`67.77%`), but many values are short evidence-like snippets, addresses, account names, or duplicated source text, not curated DJ biographies.
  - `entities.aliases`: `479110/1456325` (`32.90%`)
  - no separate public `label`, `crew`, `collective`, `record_label`, or label-affiliation contract exists in the old pack.

Verified later repair facts:

- DB1 raw `atlas.sqlite` after current known state:
  - `articles.publish_time`: `117906/139123` (`84.75%`)
  - `events.time_iso`: `371071/609235` (`60.91%`)
  - `events.city`: `299405/609235` (`49.14%`)
  - `events.place`: `467570/609235` (`76.75%`)
  - `entities.bio`: `1026990/1515202` (`67.78%`)
  - `entities.city`: `0/1515202`
- `atlas_time_text_deep_parse_20260528`:
  - `newly_parsed=58042`
  - `final_with_time_iso=428199/609235` (`70.28%`)
  - `final_without_time_iso=181036`
  - This improves time coverage but still leaves a large unresolved date bucket.
- `atlas_pubtime_backfill_20260528`:
  - `articles.publish_time` improved from `117906/139123` (`84.7%`) to `122680/139123` (`88.2%`)
  - `total_backfilled=4774`
  - remaining without publish time: `16443`
- `atlas_llm_extraction_20260528`:
  - city/geocode fill: `88794`
  - city extraction direct LLM fill: `59`, remaining sample `941`
  - time parsing fill: `918`, remaining sample `82`
  - final reported state: `city_filled=299405`, `city_empty=168505`, `time_filled=371071`, `time_empty=209627`
- `atlas_city_place_extract_20260528`:
  - `city_filled_before=19042`
  - `city_filled_after=210711`
  - `newly_extracted=191669`
  - `percent_filled=34.6`
  - `still_empty_place_exists=257199`
- Current DB2 serving projection:
  - `performance_event.starts_at`: `354066/508049` (`69.69%`)
  - `performance_event.city`: `387910/508049` (`76.35%`)
  - `performance_event.venue_name`: `441433/508049` (`86.89%`)
  - `dj_event.starts_at`: `856251/1285827` (`66.59%`)
  - `dj_event.city`: `974885/1285827` (`75.82%`)
  - `dj_event.venue_name`: `1134596/1285827` (`88.24%`)
- Current DB3 miniapp projection:
  - `dj_event.starts_at`: `653724/899497` (`72.68%`)
  - `dj_event.city`: `663015/899497` (`73.71%`)
  - `dj_profile.bio`: `1137/53459` (`2.13%`)
  - `dj_profile.bio_source`: mostly empty; non-empty sources are mainly `soundcloud`, `youtube`, `mixcloud`, and `ra`.
- Current subject taxonomy has `organizer` rows labeled as `厂牌/Crew/主办` in `taxon_path`, but this is a broad subject class, not a clean artist-to-label affiliation field.

Diagnosis:

- The old DeepSeek superlongrun did not basically miss everything. It captured many article, entity, event, evidence, participant, organizer, place, and time-text surfaces.
- It did basically miss or defer the fields the product now cares about most: source-backed publish date, resolved event date, resolved city, canonical venue, curated DJ bio, artist-label/crew affiliation, and public-safe external profile/media links.
- The old schema was a generic graph candidate schema. It had `entities`, `events`, `relations`, `claims`, and `evidence`; it did not preserve the richer activity contract: source line, poster OCR block, lineup rows, start/end time, door time, ticketing, address, venue alias, organizer role, artist billing, label affiliation, and confidence-by-field.
- Later补抓 scripts were real and useful, but they were patch lanes, not a unified contract:
  - time-text parsing improved event dates but left unresolved relative/ambiguous dates,
  - publish-time backfill improved article dates but did not close all articles,
  - city extraction improved city coverage but did not become a lossless venue/address model,
  - bio deployment exposed a field in the serving surface, but DB3 bio coverage remains low.
- Therefore the new E-drive database must not be built by replaying old DeepSeek JSONL directly. It must ingest old outputs as a source evidence layer and rebuild canonical event/profile/label tables through field-level lineage and quality gates.

## Rethought DeepSeek Pipeline

New pipeline principle: evidence first, typed extraction second, deterministic repair third, LLM adjudication last. Do not ask one generic DeepSeek pass to produce the final database.

Target lanes:

1. Source Artifact Lane
   - Inputs: raw WeChat HTML/MD, mptext/archive status, article metadata, poster images/OCR, existing old DeepSeek JSONL.
   - Output tables: `source_article`, `source_artifact`, `source_text_block`, `source_ocr_block`, `source_lineage`.
   - Rule: preserve source identity and artifact quality before entity/event extraction.

2. Activity Extraction Lane
   - Extract event title, event kind, start/end date, time text, door time, venue, address, city, ticket fields, lineup lines, organizer lines, and evidence snippets.
   - Output tables: `event_candidate`, `lineup_candidate`, `venue_candidate`, `organizer_candidate`, `time_candidate`.
   - Rule: every field has `source_ref_id`, `source_span`, `extractor`, `confidence`, and `state`.

3. Profile And Bio Lane
   - Inputs: current DB2 profiles, DB3 bios, companion DB, outlink/social sidecars, RA/SoundCloud/Bandcamp/Youtube/Mixcloud metadata where gates allow.
   - Output tables: `profile_candidate`, `bio_candidate`, `external_profile_candidate`, `media_candidate`.
   - Rule: old entity `bio` is evidence text, not a public bio unless it passes profile/source matching.

4. Label/Crew/Affiliation Lane
   - Separate `organization` from label/crew/promoter/venue/media.
   - Output tables: `org_candidate`, `label_candidate`, `artist_label_edge_candidate`, `crew_membership_candidate`, `promoter_event_edge`.
   - Rule: `厂牌/Crew/主办` taxon is a starting class only; public affiliation requires source-backed relation evidence.

5. Deterministic Repair Lane
   - Use article publish time, account calendar distribution, title dates, venue-city registry, address parser, and known venue maps before LLM.
   - Output tables: `date_resolution`, `city_resolution`, `venue_resolution`, `field_repair_audit`.
   - Rule: high-confidence deterministic repairs can promote to staging; ambiguous relative dates remain blocked.

6. LLM Adjudication Lane
   - Use DeepSeek only for bounded unresolved queues: ambiguous time, ambiguous venue, identity merge, label affiliation, bio attribution.
   - Output tables: `llm_decision`, `llm_prompt_trace_redacted`, `adjudication_queue`.
   - Rule: LLM writes decisions to sidecar/state tables only; canonical tables are updated by separate write gates.

7. Projection Lane
   - Build DB2/DB3 serving read models from canonical/staging layers.
   - Output tables: `projection_audit`, `db2_gap`, `db3_projection_loss`, `public_field_gate`.
   - Rule: missing fields must be explained as `source_missing`, `extract_missing`, `blocked`, `projection_intentional`, or `bug`.

### Task 13: DeepSeek Legacy Quality Audit Report

**Files:**
- Create: `tools/stage7_rewrite/scripts/audit_deepseek_legacy_extraction_quality.py`
- Create: `tools/stage7_rewrite/tests/test_audit_deepseek_legacy_extraction_quality.py`

- [ ] **Step 1: Test old release-pack field coverage**

```python
def test_legacy_pack_reports_missing_date_city_but_keeps_evidence(tmp_path):
    pack = make_release_pack(
        tmp_path,
        articles=[{"article_uid": "a1", "title": "T", "publish_time": ""}],
        events=[{"source_article_uid": "a1", "name": "E", "time_text": "今晚", "time_iso": "", "city": "", "place": "OIL"}],
        entities=[{"source_article_uid": "a1", "name": "DJ A", "type": "person", "bio": "snippet"}],
    )
    report = audit_legacy_pack(pack)
    assert report["coverage"]["events"]["time_iso"]["pct"] == 0
    assert report["coverage"]["events"]["time_text"]["non_empty"] == 1
    assert report["decision"] == "legacy_deepseek_pack_use_as_evidence_not_canonical"
```

- [ ] **Step 2: Implement stream-safe JSONL coverage audit**

The script must stream the old release-pack JSONL files and report:

- article date/source coverage,
- event time/city/place/participant/organizer coverage,
- entity name/type/bio/alias/city coverage,
- missing product fields: curated bio, label affiliation, source span, resolved event date, venue id, source ref id,
- current DB1/DB2/DB3 comparison if DB paths are provided.

No source body, raw URL, image, or secret should be copied into the report.

Default command:

```powershell
python tools\stage7_rewrite\scripts\audit_deepseek_legacy_extraction_quality.py --pack-dir tools\stage7_rewrite\reports\consumer_release_pack_all_deepseek_127511_20260520 --db1 reports\atlas_incremental_wechat_refresh_20260522_1438\atlas_local_sqlite_db_139123_activity_candidate_current_20260525_1435\atlas.sqlite --db2 reports\atlas_serving_time_overlay_span_split_search_date_refresh_candidate_20260527_2018\atlas_serving.sqlite --db3 services\weekly_activity_cloudrun\data\atlas_miniapp.sqlite --out-dir tools\stage7_rewrite\reports\deepseek_legacy_quality_audit_20260601
```

Expected:

```text
decision=legacy_deepseek_pack_use_as_evidence_not_canonical
database_mutations=false
raw_body_copied=false
```

### Task 14: New Activity-Profile-Label Pipeline Contract

**Files:**
- Create: `tools/stage7_rewrite/contracts/atlas_activity_profile_label_pipeline_v1.json`
- Create: `tools/stage7_rewrite/tests/test_atlas_activity_profile_label_pipeline_contract.py`

- [ ] **Step 1: Test required contract lanes**

```python
def test_pipeline_contract_has_separate_activity_profile_label_lanes(contract):
    lane_names = {lane["name"] for lane in contract["lanes"]}
    assert {"source_artifact", "activity_extraction", "profile_bio", "label_affiliation", "deterministic_repair", "llm_adjudication", "projection"}.issubset(lane_names)
```

- [ ] **Step 2: Define field-level state rules**

The contract must require each extracted field to carry:

- `source_ref_id`
- `source_artifact_id`
- `source_span_or_block_id`
- `extractor`
- `extractor_version`
- `confidence`
- `state`: `raw`, `candidate`, `deterministic_repaired`, `llm_adjudicated`, `blocked`, `public_fact`
- `block_reason`
- `projection_target`

### Task 15: Bio And Label Goldmine Queue

**Files:**
- Create: `tools/stage7_rewrite/scripts/build_bio_label_goldmine_queue.py`
- Create: `tools/stage7_rewrite/tests/test_build_bio_label_goldmine_queue.py`

- [ ] **Step 1: Build source-ranked queues**

Queue sources, in this order:

1. DB3 `dj_profile.bio` rows with `bio_source`.
2. Companion/social profile sidecars with profile metadata.
3. Old DeepSeek entity `bio` snippets that match a DB2/DB3 subject by stable name plus source evidence.
4. Organization rows whose context implies label/crew/promoter/venue/media.
5. External profiles with rights-safe text metadata.

- [ ] **Step 2: Keep promotion blocked by default**

Output:

- `bio_candidate_queue.jsonl`
- `label_affiliation_candidate_queue.jsonl`
- `bio_label_coverage_summary.json`

Rows must default to `candidate` or `blocked`; no public bio or label edge is promoted without a later adjudication/write gate.

### Task 16: DDownload Release V2 Source Artifact Audit

**Files:**
- Create: `tools/stage7_rewrite/scripts/audit_ddownload_release_v2_source_artifacts.py`
- Create: `tools/stage7_rewrite/tests/test_audit_ddownload_release_v2_source_artifacts.py`

- [ ] **Step 1: Test manifest/index consistency without root recursion**

```python
def test_ddownload_release_manifest_matches_index_without_raw_copy(tmp_path):
    root = make_release_v2_fixture(tmp_path, total_articles=2)
    report = audit_release_v2(root)
    assert report["manifest"]["total_articles"] == 2
    assert report["index"]["rows"] == 2
    assert report["safety"]["ddownload_root_recursive_scan"] is False
    assert report["safety"]["raw_html_copied"] is False
```

- [ ] **Step 2: Implement release V2 metadata audit**

Real source:

`D:\DDownload\_llm_release_v2`

The audit must read only:

- `manifest.json`
- `index.jsonl` as a stream
- first-level `articles` account directories
- per-article file-name/size presence for a bounded sample
- `quality_report.json`, `meta.json`, and sidecar keys for bounded samples

It must not read:

- root cookie/key files,
- raw HTML/MHTML/PDF,
- full `llm_input.md` bodies by default,
- raw source URL lists beyond hashed/token metadata,
- DDownload root recursively.

Required outputs:

- `ddownload_release_v2_manifest_audit.json`
- `ddownload_release_v2_account_rollup.jsonl`
- `ddownload_release_v2_sample_file_presence.jsonl`
- `ddownload_release_v2_goldmine_recommendations.md`

Required interpretation:

- promote `_llm_release_v2` to the first source-artifact candidate for the new E-drive DB staging plan,
- treat blank `post_date` in `_llm_release_v2/index.jsonl` and sampled `meta.json` as release projection loss, not as unrecoverable source-date loss,
- repair release article dates only through bounded queue lineage on `(account, token)`, with duplicate-key and failed-key reports,
- use `_archive_mptext` only for missing-source recovery and not as public evidence,
- use `_llm_artifacts` status as historical export evidence,
- keep root-level cookie/key/api files excluded.

### Task 17: DDownload Queue-To-Release Date Lineage Audit

**Files:**
- Create: `tools/stage7_rewrite/scripts/audit_ddownload_queue_release_lineage.py`
- Create: `tools/stage7_rewrite/tests/test_audit_ddownload_queue_release_lineage.py`

- [ ] **Step 1: Test queue date repair without copying raw URLs**

```python
def test_queue_release_join_recovers_release_dates_without_raw_url_export(tmp_path):
    queue = tmp_path / "download_ready_queue.jsonl"
    release = tmp_path / "index.jsonl"
    write_jsonl(queue, [
        {"account": {"nickname": "Club A"}, "token": "t1", "post_date": "2026-04-01", "url": "https://example.invalid/a"},
        {"account": {"nickname": "Club A"}, "token": "t2", "post_time": 1775001600, "url": "https://example.invalid/b"},
    ])
    write_jsonl(release, [
        {"account": "Club A", "token": "t1", "post_date": ""},
        {"account": "Club A", "token": "t2", "post_date": ""},
    ])
    report = audit_queue_release_lineage(queue, release, tmp_path / "out")
    assert report["release_rows"] == 2
    assert report["release_matched_queue"] == 2
    assert report["release_matched_queue_with_date"] == 2
    assert report["safety"]["raw_source_urls_exported"] is False
```

- [ ] **Step 2: Implement streaming join and duplicate-key accounting**

Real sources:

- `D:\DDownload\_queues\download_ready_queue.jsonl`
- `D:\DDownload\_llm_release_v2\index.jsonl`

The audit must:

- stream the queue and build a bounded key index keyed by normalized `(account, token)`,
- stream the release index and join each release row back to the queue key,
- record `queue_rows=93761`, `queue_unique_keys=93253`, `release_rows=93000`, `release_matched_queue=93000`, and `release_missing_queue=0` on the current readback,
- record `release_matched_queue_with_date=93000` and `release_missing_queue_date=0`,
- record duplicate queue keys separately: `queue_duplicate_keys=4`, `duplicate_extra_rows=508`,
- record failed queue keys separately: `queue_unique_not_in_release=253`,
- roll up failed keys by account; current readback is `EchoBay=158`, `ClubCeliaShanghai=89`, `电容DeepRoll=2`, `Dada Bar Beijing=2`, `Dada Kunming=1`, `EXIT Shanghai=1`.

It must not:

- recurse into `D:\DDownload`,
- open root-level cookie/key/api files,
- export raw `source_url`, `cover_url`, cookies, tokens beyond the existing release `token` key needed for lineage,
- copy full `llm_input.md` bodies.

Required outputs:

- `ddownload_queue_release_lineage_audit.json`
- `ddownload_release_v2_date_repair_candidates.jsonl`
- `ddownload_queue_duplicate_keys.jsonl`
- `ddownload_queue_failed_keys_by_account.jsonl`

Required interpretation:

- `_llm_release_v2` is usable as the source-artifact layer for the new E-drive staging plan only if the queue-lineage date repair is applied before canonical event/profile extraction.
- The `253` failed unique queue keys stay in a recovery queue and must not be counted as successfully copied release articles.
- The repaired article date is source article metadata; event dates still require separate event-level parsing from `llm_input.md`, `poster_ocr.json`, and DeepSeek/Stage7 extracted event candidates.

## File Structure

Planned files for implementation:

- Create: `C:\code\githubstar\wechathtmldownload\tools\stage7_rewrite\contracts\atlas_unified_field_matrix_v1.json`
  - Machine-readable field matrix and state rules.
- Create: `C:\code\githubstar\wechathtmldownload\tools\stage7_rewrite\scripts\build_atlas_unified_field_matrix.py`
  - Reads schema from DB1/DB2/DB3/sidecars and writes matrix reports.
- Create: `C:\code\githubstar\wechathtmldownload\tools\stage7_rewrite\tests\test_build_atlas_unified_field_matrix.py`
  - Verifies contract generation on tiny SQLite fixtures.
- Create: `C:\code\githubstar\wechathtmldownload\tools\stage7_rewrite\scripts\audit_atlas_lineage_goldmine.py`
  - Runs the read-only lineage/goldmine audits.
- Create: `C:\code\githubstar\wechathtmldownload\tools\stage7_rewrite\tests\test_audit_atlas_lineage_goldmine.py`
  - Verifies DB1/DB2/DB3 gap detection, projection loss detection, and state labeling.
- Create: `C:\code\githubstar\wechathtmldownload\tools\stage7_rewrite\scripts\audit_ddownload_release_v2_source_artifacts.py`
  - Audits release V2 manifest/index/sample file presence without root recursion or raw body copying.
- Create: `C:\code\githubstar\wechathtmldownload\tools\stage7_rewrite\tests\test_audit_ddownload_release_v2_source_artifacts.py`
  - Verifies release V2 audit safety gates and output counts on tiny fixtures.
- Create: `C:\code\githubstar\wechathtmldownload\tools\stage7_rewrite\scripts\audit_ddownload_queue_release_lineage.py`
  - Audits queue-to-release key lineage and date repair candidates.
- Create: `C:\code\githubstar\wechathtmldownload\tools\stage7_rewrite\tests\test_audit_ddownload_queue_release_lineage.py`
  - Verifies queue date repair, duplicate-key accounting, failed-key isolation, and raw URL non-export.
- Modify: `C:\code\githubstar\wechathtmldownload\package.json`
  - Add `weekly:atlas-unified:field-matrix` and `weekly:atlas-unified:lineage-goldmine`.
- Later after reports pass: create E-drive DB build plan separately; do not combine with this read-only audit.

## Task 1: Field Matrix Contract

**Files:**
- Create: `tools/stage7_rewrite/contracts/atlas_unified_field_matrix_v1.json`
- Test: `tools/stage7_rewrite/tests/test_build_atlas_unified_field_matrix.py`

- [ ] **Step 1: Write the contract fixture test**

```python
def test_contract_has_required_families_and_state_rules(matrix_contract):
    families = {row["family"] for row in matrix_contract["fields"]}
    assert {"identity", "event", "relation", "evidence", "external", "audit"}.issubset(families)
    assert matrix_contract["state_values"] == [
        "public_fact",
        "candidate",
        "report_only",
        "review_ready",
        "blocked",
        "production_effective",
    ]
    source_ref = next(row for row in matrix_contract["fields"] if row["unified_field"] == "source_ref_id")
    assert source_ref["rule"] == "Primary evidence lookup key; sourceHash is not a substitute."
```

- [ ] **Step 2: Add the contract JSON**

```json
{
  "schema_version": "atlas_unified_field_matrix.v1",
  "state_values": ["public_fact", "candidate", "report_only", "review_ready", "blocked", "production_effective"],
  "merge_rules": {
    "source_ref_id": "Primary evidence lookup key; sourceHash is not a substitute.",
    "non_empty_preservation": "Empty overlay values never overwrite non-empty DB1/DB2/DB3 fields.",
    "venue_scope": "City-scoped venue keys win before plain venue names or ids.",
    "sidecar_promotion": "Sidecar rows remain candidate/report_only until explicit gates pass."
  },
  "fields": [
    {
      "family": "identity",
      "unified_field": "subject_id",
      "db1": ["entities.eid", "events.evid"],
      "db2": ["canonical_subject.subject_id", "dj_profile.dj_id"],
      "db3": ["subject.subject_id", "dj_profile.dj_id"],
      "sidecar": ["dj_identity_candidates.subject_id", "external_link_candidates.entity_search_id"],
      "rule": "DB2 id wins for public facts; sidecar ids stay candidate."
    },
    {
      "family": "evidence",
      "unified_field": "source_ref_id",
      "db1": ["events.source_article_uid", "atlas_activity_evidence_refs.evidence_ref_id"],
      "db2": ["evidence_ref.source_ref_id", "performance_event.source_ref_id", "dj_event.source_ref_id"],
      "db3": ["source_ref.source_ref_id", "dj_event.source_ref_id"],
      "sidecar": ["external_link_candidates.source_ref", "interviewStore.sourceRefId"],
      "rule": "Primary evidence lookup key; sourceHash is not a substitute."
    }
  ]
}
```

- [ ] **Step 3: Run the focused contract test**

Run:

```powershell
python -m pytest tools\stage7_rewrite\tests\test_build_atlas_unified_field_matrix.py -q
```

Expected:

```text
1 passed
```

## Task 2: Matrix Builder Script

**Files:**
- Create: `tools/stage7_rewrite/scripts/build_atlas_unified_field_matrix.py`
- Test: `tools/stage7_rewrite/tests/test_build_atlas_unified_field_matrix.py`

- [ ] **Step 1: Extend the test to create tiny DB1/DB2/DB3 fixtures**

```python
def test_matrix_builder_reads_db_schemas_and_counts(tmp_path):
    db1 = tmp_path / "db1.sqlite"
    db2 = tmp_path / "db2.sqlite"
    db3 = tmp_path / "db3.sqlite"
    create_sqlite(db1, {"events": ["evid", "name", "time_iso", "source_article_uid"]})
    create_sqlite(db2, {"performance_event": ["event_id", "event_title", "starts_at", "source_ref_id"]})
    create_sqlite(db3, {"dj_event": ["dj_id", "event_id", "starts_at", "source_ref_id"]})
    report = build_report(
        contract_path=tmp_path / "contract.json",
        db_paths={"db1": db1, "db2": db2, "db3": db3},
        out_dir=tmp_path / "out",
    )
    assert report["decision"] == "atlas_unified_field_matrix_ready_report_only"
    assert report["db_layers"]["db1"]["tables"]["events"]["count"] == 1
    assert report["safety"]["database_mutations"] is False
```

- [ ] **Step 2: Implement the script with read-only SQLite opening**

Implementation requirements:

```python
def sqlite_connect_readonly(path: Path) -> sqlite3.Connection:
    return sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)

def table_schema_and_count(path: Path, table: str) -> dict[str, Any]:
    with sqlite_connect_readonly(path) as conn:
        found = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if table not in found:
            return {"exists": False, "count": 0, "columns": []}
        columns = [row[1] for row in conn.execute(f'PRAGMA table_info("{table}")')]
        count = int(conn.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0])
        return {"exists": True, "count": count, "columns": columns}
```

The script must write:

- `tools/stage7_rewrite/reports/atlas_unified_field_matrix_YYYYMMDD/atlas_unified_field_matrix.json`
- `tools/stage7_rewrite/reports/atlas_unified_field_matrix_YYYYMMDD/atlas_unified_field_matrix.md`

Report safety fields must be:

```json
{
  "report_only": true,
  "database_mutations": false,
  "provider_calls_performed": false,
  "model_calls_performed": false,
  "deployment_executed": false,
  "secrets_read": false
}
```

- [ ] **Step 3: Verify**

Run:

```powershell
python -m py_compile tools\stage7_rewrite\scripts\build_atlas_unified_field_matrix.py
python -m pytest tools\stage7_rewrite\tests\test_build_atlas_unified_field_matrix.py -q
```

Expected:

```text
py_compile passes
tests pass
```

## Task 3: Lineage Goldmine Audit

**Files:**
- Create: `tools/stage7_rewrite/scripts/audit_atlas_lineage_goldmine.py`
- Test: `tools/stage7_rewrite/tests/test_audit_atlas_lineage_goldmine.py`

- [ ] **Step 1: Write fixture tests for missing event and projection loss**

```python
def test_goldmine_finds_db1_event_missing_from_db2(tmp_path):
    db1 = tmp_path / "db1.sqlite"
    db2 = tmp_path / "db2.sqlite"
    db3 = tmp_path / "db3.sqlite"
    create_sqlite(db1, {"events": ["evid", "name", "city", "time_iso", "participants_json", "source_article_uid"]})
    create_sqlite(db2, {"performance_event": ["event_id", "event_title", "city", "starts_at", "source_ref_id"]})
    create_sqlite(db3, {"dj_event": ["dj_id", "event_id", "source_ref_id"], "source_ref": ["source_ref_id"]})
    insert(db1, "events", {"evid": "event:gold", "name": "Gold Night", "city": "上海", "time_iso": "2026-05-01", "participants_json": "[\"DJ A\"]", "source_article_uid": "src:1"})
    report = audit_lineage(db1, db2, db3, out_dir=tmp_path / "out")
    assert report["goldmine"]["db1_event_not_in_db2"]["count"] == 1
    assert report["goldmine"]["db1_event_not_in_db2"]["rows"][0]["event_id"] == "event:gold"

def test_goldmine_finds_db3_missing_source_ref(tmp_path):
    db2 = create_db2_with_evidence(tmp_path / "db2.sqlite", source_ref_id="src:1")
    db3 = create_db3_with_missing_source_ref(tmp_path / "db3.sqlite", event_source_ref_id="src:1")
    report = audit_lineage(db1=None, db2=db2, db3=db3, out_dir=tmp_path / "out")
    assert report["projection_loss"]["db3_missing_source_ref_count"] == 1
```

- [ ] **Step 2: Implement stable selectors**

Use these selectors first:

```python
DB1_EVENT_KEY = "events.evid"
DB2_EVENT_KEY = "performance_event.event_id"
DB3_EVENT_KEY = "dj_event.event_id"
SOURCE_REF_KEY = "source_ref_id"
DJ_KEY = "dj_id"
VENUE_KEY = "venue_id"
NORMALIZED_NAME_KEY = "normalized_name"
```

Use row-count differences as summary signals and set-based queries as samples. Do not materialize all row payloads in memory when a count query is enough.

- [ ] **Step 3: Implement report sections**

The JSON report must include:

```json
{
  "schema_version": "atlas_lineage_goldmine_audit.v1",
  "decision": "atlas_lineage_goldmine_ready_report_only",
  "db_authority": {},
  "lineage_counts": {},
  "projection_loss": {},
  "goldmine": {},
  "blockers": {},
  "next_gates": [],
  "safety": {}
}
```

Required sections:

- `lineage_counts.db1_events`
- `lineage_counts.db2_performance_event`
- `projection_loss.db2_to_db3_dj_event_delta`
- `projection_loss.db2_to_db3_source_ref_delta`
- `goldmine.db1_event_not_in_db2`
- `goldmine.structured_evidence_drawer_candidates`
- `goldmine.external_link_projection_candidates`
- `blockers.relation_identity_write_gate`
- `blockers.t6_year_context_source_artifact_required`

- [ ] **Step 4: Verify**

Run:

```powershell
python -m py_compile tools\stage7_rewrite\scripts\audit_atlas_lineage_goldmine.py
python -m pytest tools\stage7_rewrite\tests\test_audit_atlas_lineage_goldmine.py -q
```

Expected:

```text
py_compile passes
tests pass
```

## Task 4: Real Read-Only Audit Run

**Files:**
- Output only under: `tools/stage7_rewrite/reports/atlas_lineage_goldmine_YYYYMMDD/`

- [ ] **Step 1: Run field matrix on real DB paths**

Run:

```powershell
python tools\stage7_rewrite\scripts\build_atlas_unified_field_matrix.py --out-dir tools\stage7_rewrite\reports\atlas_unified_field_matrix_20260601
```

Expected:

```text
decision=atlas_unified_field_matrix_ready_report_only
database_mutations=false
```

- [ ] **Step 2: Run lineage goldmine audit on real DB paths**

Run:

```powershell
python tools\stage7_rewrite\scripts\audit_atlas_lineage_goldmine.py --out-dir tools\stage7_rewrite\reports\atlas_lineage_goldmine_20260601
```

Expected:

```text
decision=atlas_lineage_goldmine_ready_report_only
database_mutations=false
```

- [ ] **Step 3: Inspect only summary counts**

The operator should inspect these values first:

- DB1-only event candidates count.
- DB2-to-DB3 `dj_event` delta.
- DB2-to-DB3 `source_ref` delta.
- Structured evidence drawer candidate count.
- External-link projection candidate count.
- Identity blocker count and approved write-gate count.

## Task 5: Package The E-Drive DB Build Decision

**Files:**
- Create after Task 4 passes: `reports/ATLAS_UNIFIED_E_DRIVE_DB_BUILD_DECISION_20260601.md`

- [ ] **Step 1: Write a decision report, not a database**

The report must answer:

- Which fields are safe public facts now.
- Which fields are candidate/report-only.
- Which fields are blocked by identity/source/artifact gates.
- Which high-value DB1 fields should be promoted into a future staging layer.
- Whether E-drive build should use SQLite-only or DuckDB staging plus SQLite serving.

- [ ] **Step 2: Gate E-drive database creation**

E-drive database creation remains blocked until:

- Field matrix report exists and has no high findings.
- Lineage goldmine report exists.
- DB1/DB2 event delta is categorized.
- DB2/DB3 projection loss is explained or accepted as intended projection.
- Relation identity write gate remains separated from public serving facts.
- External-link `db2_projection_allowed` is non-zero only after bounded fetch/copyright/leak gates pass.

## Task 6: Package Scripts And Docs Hooks

**Files:**
- Modify: `package.json`
- Modify after report generation: `docs/current-runtime.md`
- Modify after report generation: `docs/DOCUMENTATION_INDEX.md`

- [ ] **Step 1: Add package scripts**

Add:

```json
{
  "weekly:atlas-unified:field-matrix": "python tools/stage7_rewrite/scripts/build_atlas_unified_field_matrix.py",
  "weekly:atlas-unified:lineage-goldmine": "python tools/stage7_rewrite/scripts/audit_atlas_lineage_goldmine.py"
}
```

- [ ] **Step 2: Run package script smoke**

Run:

```powershell
npm run weekly:atlas-unified:field-matrix -- --out-dir tools\stage7_rewrite\reports\atlas_unified_field_matrix_smoke
npm run weekly:atlas-unified:lineage-goldmine -- --out-dir tools\stage7_rewrite\reports\atlas_lineage_goldmine_smoke
```

Expected:

```text
both commands finish with report_only=true and database_mutations=false
```

## Self-Review Checklist

- The plan keeps DB1 raw/source, DB2 serving, DB3 miniapp projection, and sidecars separate.
- The plan does not authorize E-drive DB creation yet.
- The field matrix includes source/evidence, relation, external-link, media, and audit state fields.
- The goldmine audit explicitly searches for DB1 fields missing from DB2 and DB2 fields missing from DB3.
- The relation identity blocker remains a blocker, not an implied merge task.
- The S119 external-link sidecar remains candidate/report-only.
- No destructive Git, DB mutation, network crawl, provider, LLM, deployment, mini-program upload, memory write, or secret read is part of this plan.
