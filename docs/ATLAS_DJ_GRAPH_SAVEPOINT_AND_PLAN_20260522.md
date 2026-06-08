# Atlas DJ Graph Savepoint And Plan

Updated: 2026-05-22 03:01 CST

Project: `C:\code\githubstar\wechathtmldownload`

Audience: future Codex / OpenClaw / DeepSeekTUI agents and the project owner.

Purpose: preserve the current Atlas plan documents, important findings, pitfalls, highlights, and next execution path so the DJ-first graph work can resume without relying on chat history.

## Main Problem

Atlas is not just a generic knowledge graph site. It is a China underground electronic music historical memory system where DJ / artist nodes are primary, and events, venues, labels, radio/media, works, social profiles, and source articles are evidence/context around DJs.

The immediate product risk is false completeness: the raw database is large, but the current public graph/profile API can still look incomplete if it uses exact names, old graph markers, or article-neighborhood windows instead of DJ-first canonical rollups.

## Scope

In scope:

- `C:\code\githubstar\wechathtmldownload`
- Local Atlas SQLite read model: `tools\stage7_rewrite\reports\atlas_local_sqlite_db_138102_20260521\atlas.sqlite`
- DJ-first graph architecture, repair sidecars, profile/search API correctness, and future `atlas_serving.sqlite`
- Public deployment target: `atlas.huaidj.club`
- Public anti-scrape boundary and dark-database design

Out of scope unless the owner explicitly reopens it:

- Raw `atlas.sqlite` mutation
- Paid LLM/API reprocessing waves
- Neo4j/Qdrant production writes
- CloudRun deploy / mini-program upload / WeChat review
- Raw source URL public exposure
- Broad `D:\` scans
- Claude / Anthropic / old Singapore VPS Claude workflows

## Canonical Plan Documents

Read these first, in this order:

1. `docs\ATLAS_DJ_FIRST_FULL_DESIGN_AND_PLAN_20260522.md`
   - DJ-first product model and full graph plan.
   - Defines DJ/person as the primary node, events as performance facts, and articles as evidence.

2. `docs\ATLAS_HIGH_PERFORMANCE_DATABASE_ARCHITECTURE_20260522.md`
   - Current performance/database decision.
   - Raw `atlas.sqlite` stays private; public site should use immutable `atlas_serving.sqlite`.

3. `docs\ATLAS_MUSIC_GRAPH_RELATION_LOGIC_CHINESE_UI_20260521.md`
   - Chinese UI and graph lens logic: DJ career, venue ecosystem, label network, event lineup, work context.

4. `docs\ATLAS_GRAPH_DB_SEARCH_TAXONOMY_ARCHITECTURE_20260521.md`
   - One-box search, taxonomy, serving/search split, and mini-program/LLM bridge architecture.

5. `docs\ATLAS_FULL_GRAPH_HIGH_PERFORMANCE_ARCHITECTURE_20260521.md`
   - Full-load / high-performance graph rendering and graph-DB benchmark notes.

6. `docs\ATLAS_GRAPH_EXPLORER_WEB_DESIGN_20260521.md`
   - Current `/atlas/graph` workbench design, API boundaries, Chinese UI sections, and security gate.

7. `docs\ATLAS_GRAPH_FULL_ENTITY_PROFILE_ROLLUP_20260522.md`
   - Implemented exact-name profile rollup design. It is useful but now partially superseded by the canonical-alias fix recorded in `docs\current-runtime.md`.

8. `docs\ATLAS_ANTI_SCRAPE_SECURITY_PLAN_20260521.md`
   - Anti-scrape and dark-database deployment gate.

9. `docs\ATLAS_CLOUDFLARE_LOW_COST_DEPLOY_STEPS_20260521.md`
   - Cloudflare Free/Turnstile/Nginx low-cost deployment runbook for `atlas.huaidj.club`.

10. `docs\ATLAS_SOCIAL_SEARCH_RULES_SSOT_20260521.md`
    - Social/outlink search rules and public evidence acceptance boundary.

11. `docs\superpowers\plans\2026-05-22-atlas-dj-first-canonical-rollup.md`
    - First safe canonical canary / rollup implementation plan.

Supporting current evidence:

- `reports\atlas_dj_product_loss_chain_20260522\audit.md`
- `reports\atlas_dj_repair_priority_queue_20260522\summary.md`
- `reports\atlas_dj_low_cost_repair_sidecar_20260522\summary.md`
- `reports\atlas_source_url_recovery_20260522\summary.md`
- `reports\atlas_event_time_normalized_sidecar_20260522\summary.md`
- `reports\atlas_dj_first_canary_20260522\summary.md`
- `reports\atlas_dj_history_rollup_top25_20260522\summary.md`
- `reports\atlas_graph_search_selftest_20260521T181135Z\atlas_graph_search_selftest.md`
- `docs\ATLAS_SERVING_READ_MODEL_PRODUCTION_RUN_20260522.md`
- `reports\atlas_serving_read_model_20260522\summary.md`
- `docs\ATLAS_FULL_REPAIR_PRIVATE_CANDIDATE_20260522.md`
- `docs\ATLAS_FULL_RUN_AND_REPAIR_WORKLOG_20260522.md`
- `reports\atlas_serving_repair_full_private_20260522\summary.md`

## Full Serving Candidate Result

The planned `atlas_serving.sqlite` gate has now been executed.

- Builder: `tools\stage7_rewrite\scripts\build_atlas_serving_read_model.py`
- Test: `tools\stage7_rewrite\tests\test_build_atlas_serving_read_model.py`
- Serving DB: `reports\atlas_serving_read_model_20260522\atlas_serving.sqlite`
- Full run scanned `608,678` raw events.
- Public-safe materialized output:
  - `467,769` performance events
  - `51,593` DJ profiles
  - `1,104,301` DJ-event edges
  - `611,140` directed DJ relation edges
  - `103,231` DJ-venue rollups
  - `296,365` DJ-org rollups
  - `547,374` search documents
  - `51,593` graph windows
- Event ID pitfall fixed: old `source_uid#evid` folding would have skipped `409,222` events. New public event IDs are hashed from source, row, local ID, title/time/place and do not expose raw article UID.
- Product-noise pitfall fixed: wine/menu/product events are blocked before public DJ history/search/graph materialization. Final `wine_search_hits=0`.
- Security boundary verified: public serving schema has no `source_url`, `archive_raw_html_path`, `raw_json`, or `article_uid` columns; public text hits for `mp.weixin`, `raw.html`, and `D:/` are `0`; `public_url_allowed != 0` is `0`.
- MaFoL proof: search top result is `dj / MaFoL`; profile has `149` events, `108` collaborators, and a precomputed graph window.

This is still local production-candidate state. It has not been deployed to the Singapore VPS or CloudRun.

## Full Private Repair Candidate Result

The full repair candidate has also been executed as a private review artifact.

- Builder mode: `participant_acceptance=aggressive-private`
- Private DB: `reports\atlas_serving_repair_full_private_20260522\atlas_serving.sqlite`
- Deploy flag: `deployable_public=0`
- Full private output:
  - `538,034` performance events
  - `55,791` DJ profiles
  - `1,415,016` DJ-event edges
  - `772,998` directed DJ relation edges
  - `109,705` DJ-venue rollups
  - `324,151` DJ-org rollups
  - `623,336` search documents
  - `55,791` graph windows
- Delta over the strict public candidate:
  - `+70,265` performance events
  - `+4,198` DJ profiles
  - `+310,715` DJ-event edges
  - `+161,858` directed DJ relation edges
- MaFoL private proof: `196` events, `138` collaborators.
- Remaining post-repair gaps: `25,776` missing, `37,952` not-ready, `2,649` review-only.

This private DB is for local review and promotion decisions only. Do not deploy it directly.

## 2026-05-22 Field Repair Longrun Overlay

Current report: `docs\ATLAS_FIELD_REPAIR_LONGRUN_20260522.md`.

- Builder now emits `field_missing_counts`, uses `map_geocode_places` to recover city from venue evidence, and recovers missing venue from `source_account` only when Atlas classifies the source account as a venue.
- Strict public candidate: `reports\atlas_serving_field_repair_strict_sourcevenue_20260522-0438\atlas_serving.sqlite`, `deployable_public=1`, `467,350` events, `51,547` DJ profiles, `1,103,426` DJ-event edges, `546,873` search docs, `events_recovered_city_venue_geocode=212,631`, `events_recovered_venue_source_account=22,612`.
- Private repair candidate: `reports\atlas_serving_field_repair_private_sourcevenue_20260522-0442\atlas_serving.sqlite`, `deployable_public=0`, `participant_acceptance=aggressive-private`, `537,400` events, `55,744` DJ profiles, `1,413,589` DJ-event edges, `622,619` search docs, `events_recovered_city_venue_geocode=218,874`, `events_recovered_venue_source_account=29,415`.
- Validation for both DBs: `quick_check=ok`, forbidden schema hits `0`, URL/raw text leak hits `0`, `public_url_allowed != 0` hits `0`, wine/menu/product-noise search hits `0`.
- Remaining strict `performance_event` gaps: `starts_at=172,060`, `time_text=11,263`, `venue_name=203,054`, `city=254,719`, `source_ref_id=0`.
- Boundary remains local-only: no source DB write, no deploy, no mini-program upload/review, no network/LLM call.

## Important Findings

### Product Truth

- The product is a DJ-first historical relationship network, not a generic entity explorer.
- `articles` are evidence, not product protagonists.
- `events` are historical performance facts and the most important bridge layer.
- `entities` are raw mentions and must be canonicalized before becoming durable graph nodes.
- `participants_json`, `organizers_json`, `place`, `city`, `time_text`, `source_article_uid`, and recovered source URL/post date sidecars are the main repair levers.
- Public profile/search must never require the user to pick entity type; one-box Chinese search is the right UX.

### Database Reality

Current local full SQLite read model:

- Articles: `138,102`
- Entity rows: `1,510,787`
- Event rows: `608,678`

Loss-chain audit:

- `206,121 / 608,678` events have no participants.
- `141,601 / 608,678` events have no place.
- `246,086 / 608,678` events have no organizers.
- `608,678 / 608,678` events have empty `time_iso`.
- `28,521 / 608,678` events have empty `time_text`.
- `5,284` product rows and `12,343` noise-like rows exist in raw entity output.
- Graph surface can miss local release rows: release events `608,678`, graph unique events `158,490`, release-minus-graph events `450,188`.
- DJ collaboration usable events are only `191,100`; unusable events are `417,578`.

Interpretation: full LLM produced a broad article-level atlas, not a complete DJ history product. More blind full LLM spending is not the right first fix.

### Low-Cost Repair Wins

Report-only repair sidecars already recovered a large amount of structure without paid APIs or model calls:

- `reports\atlas_dj_low_cost_repair_sidecar_20260522\atlas_dj_low_cost_repair_sidecar.sqlite`
  - participant candidates: `165,145` (`83,847` auto / `81,298` review)
  - venue candidates: `99,461` auto
  - organizer candidates: `244,450` (`146,695` auto / `97,755` review)
  - time candidates: `456,210`
  - event repair overlay: `432,231`
  - ready-for-DJ-rollup overlay: `405,342`
  - noise quarantine: `7,658`

- `reports\atlas_source_url_recovery_20260522\atlas_source_url_recovery.sqlite`
  - source URL recovered/constructed: `138,102 / 138,102`
  - exact queue URL matches: `89,845`
  - constructed from article token: `48,257`
  - missing URL: `0`
  - recovered post dates: `89,845`
  - raw HTML paths: `89,801`

- `reports\atlas_event_time_normalized_sidecar_20260522\atlas_event_time_normalized_sidecar.sqlite`
  - input time candidates: `456,210`
  - normalized sortable dates: `321,832`
  - auto candidates: `318,541`
  - review candidates: `137,669`
  - unresolved date candidates: `134,378`
  - month-day rows with inferred year from article post date: `253,268`

### DJ Rollup Proof

`reports\atlas_dj_history_rollup_top25_20260522\summary.md` proves the DJ-first materialization shape:

- DJ profiles: `25`
- DJ-event facts: `22,521`
- collaborator rollups: `9,401`
- venue rollups: `1,157`
- organization rollups: `2,260`
- media rollups: `14`
- evidence refs: `22,521`

This is the right model to scale, not a browser-side full graph dump.

### Canonical Alias Fix

The owner correctly identified that `/atlas/graph` still looked too small. Root cause: the profile API was full only for exact names.

Before fix for `OIL`:

- `entities.name='OIL'`: `9,005` rows
- distinct source articles: `8,714`
- UI showed a truncated profile, not the full venue ecosystem.

After canonical-alias fix:

- `exactEntityRows=17,848`
- `sourceArticleCount=9,924`
- `eventCount=60,573`
- `collaboratorCount=9,997`
- `organizationCount=5,241`
- `canonicalNameCount=120`
- retrieval mode: `sqlite_canonical_alias_profile_rollup`
- top venues include `OIL`, `OIL油`, `OIL Club`, `OIL CLUB`, `OIL Room2`, `深圳OIL`

The fix expands venue/org/label profiles across:

- `entities.name`
- `articles.source_account`
- `events.place`

It also rejects substring false positives such as `Boiler Room` and removes city-only place labels such as `深圳` from venue rollups.

### Verified Radio / Media Terms

These terms are not noise:

- `SHCR`
- `BYYB`
- `baihui`
- `CDCR`

They should be classified as radio/media/community music platforms unless stronger evidence says otherwise.

### Field Noise

Some values appear in the wrong field but should not be discarded:

- `c1tyA1d2er` can appear in `events.place`, but it is a DJ/artist field-noise case, not a venue.
- City-only place labels such as `深圳` must not become venue nodes.
- Room names such as `Room2`, `MAINROOM`, and `Chill Room` need venue-contained interpretation, not independent top-level clubs by default.

## Pitfalls

1. Do not use exact name as "full profile".
   - `OIL` must merge `OIL油`, `OIL Club`, `OIL CLUB`, `深圳OIL`, and source/place aliases.
   - The same applies to DADA, ALL, BO LIVE, TAG, Elevator, ZhaoDai, etc.

2. Do not push `1,510,787` entity rows or `608,678` events directly to the browser.
   - Use server-side profile rollups, one-hop/two-hop windows, graph cache, and LOD APIs.

3. Do not treat same-article co-occurrence as strong DJ relationship.
   - Strong: same event participants, repeated same-event co-performance, same label/crew.
   - Medium: repeated same venue/source/series.
   - Weak: same article mention only.

4. Do not expose raw source URLs, raw HTML paths, source DB path, raw JSON, or bulk export endpoints publicly.
   - Public evidence should be hashed/capped and human-readable, not scrapeable bulk data.

5. Do not spend paid LLM budget before deterministic repair sidecars are exhausted.
   - Local rules already recovered hundreds of thousands of candidate fields.
   - Local LLM should only review uncertain/review queues.

6. Do not call alcohol/menu/product rows "graph entities" in public surface.
   - Wine/menu/drink/product rows should be quarantined as domain noise by default.

7. Do not call source-account pages "clubs" blindly.
   - Some accounts are radios, collectives, media channels, or promoters.

8. Do not rely on old graph-production unique counts as product completeness.
   - Old graph unique event count `158,490` is much smaller than release events `608,678`.

9. Do not claim timelines are reliable from raw `time_text`.
   - `time_iso` is empty for all event rows in the current release.
   - Use normalized sidecar date confidence tiers.

10. Do not deploy raw SQLite profile path as final public performance.
    - The canonical raw profile is now correct, but OIL-style big nodes are still seconds-level.
    - Public target needs `atlas_serving.sqlite` precomputed tables.

11. Do not use Claude/Singapore Claude VPS assumptions.
    - The owner explicitly said the Singapore VPS originally for Claude is no longer needed for Claude.

12. Do not treat local service state as deployed state.
    - Local `http://127.0.0.1:18987/atlas/graph` is not CloudRun/VPS remote-effective state.

## Highlights

- The product definition is now clear: China underground electronic music DJ relation network + historical event archive.
- The low-cost sidecar route materially repairs the core loss points without new paid LLM waves.
- Source URL recovery is complete for all `138,102` articles at the private sidecar level.
- Time normalization recovered sortable dates for `321,832` candidates.
- Canonical alias profile fixed the immediate "not full" UI problem for OIL-like large venues.
- `atlas:graph:selftest` now catches search/profile regressions on real data.
- Anti-scrape plan exists and should remain a deploy blocker, not an afterthought.
- The database architecture is cost-conscious: local/offline heavy work, public capped read model.

## Next Execution Plan

### P0 - Build `atlas_serving.sqlite`

Create an immutable public-safe serving database from private raw DB + sidecars:

- `canonical_dj`
- `canonical_venue`
- `canonical_label_org`
- `canonical_radio_media`
- `performance_event`
- `dj_event_edge`
- `dj_dj_relation_rollup`
- `dj_venue_rollup`
- `dj_org_rollup`
- `dj_media_rollup`
- `evidence_ref`
- `search_document`
- `graph_window_cache`

Rules:

- Accept deterministic `auto_candidate` repair rows by default.
- Keep `review_candidate` rows behind private review UI.
- Keep raw source URLs/private archive paths out of the public serving DB.

### P1 - DJ-First Search

Build one-box Chinese search:

- No required entity-type dropdown.
- DJ/person hits rank first when intent is a person.
- Venue hits open venue ecosystem.
- Label/org/radio hits open their network context.
- Search index must include aliases, Chinese/English names, source account names, public social handles, and venue variants.

Suggested backend:

- SQLite FTS5 first.
- Benchmark Meilisearch only if FTS5 misses search p95 or ranking quality.

### P2 - DJ Profile API

Add a dedicated DJ profile endpoint backed by `atlas_serving.sqlite`:

- basic identity: canonical name, aliases, city, avatar, public links
- historical events sorted by normalized date
- frequent venues
- frequent collaborators
- label/crew/org relations
- media/radio/work/mixtape links
- evidence chain per relation

Target p95:

- DJ profile `<120 ms`
- graph window `<200 ms`
- search `<80 ms`

### P3 - Graph Windows

Do not render a full graph by default. Use focused graph windows:

- DJ career mode
- Venue ecosystem mode
- Label/crew network mode
- Event lineup mode
- Roam/explore mode

Precompute graph windows:

- center DJ + top collaborators + top venues + recent/high-confidence events
- center venue + resident/frequent DJs + historical events + labels/promoters
- center label/org + member DJs + co-hosted events + venues

### P4 - Chinese Workbench UI

The public UI should be fully Chinese:

- 搜索
- DJ 档案
- 历史演出
- 经常同台
- 常驻/常出现俱乐部
- 厂牌/组织
- 公开资料
- 证据来源
- 漫游

Use dark workbench aesthetics and dense inspector panels. Avoid generic SaaS landing-page UI.

### P5 - Anti-Scrape Deployment Gate

Before `atlas.huaidj.club` public exposure:

- Cloudflare proxied DNS
- SSL/TLS Full, later Full strict
- Turnstile Managed
- app session gate
- WAF / rate limits / bot challenge
- Nginx origin limits
- no bulk export endpoints
- honey endpoints
- capped API windows
- origin DB path never exposed

### P6 - Social / Avatar / Outlink Enrichment

When the owner finishes downloading entity external links and avatars:

- attach avatar/public links to canonical nodes, not raw mention rows
- keep candidate links behind review when confidence is low
- do not publish raw search queues
- store public profile evidence as source-backed `dj_public_profile` rows

## Current Verification

Passed:

- `node --check services\weekly_activity_cloudrun\src\stage7AtlasSqliteStore.mjs`
- `node --check services\weekly_activity_cloudrun\tests\stage7SqliteLocal.test.mjs`
- `node --test services\weekly_activity_cloudrun\tests\stage7SqliteLocal.test.mjs` -> `12/12`
- `npm run atlas:graph:selftest -- --max-seeds 12 --auto-limit 10 --graph-limit 120 --subgraph-limit 100 --related-limit 20 --seed-latency-budget-ms 300 --profile-latency-budget-ms 5000` -> `12/12`

Latest self-test evidence:

- `reports\atlas_graph_search_selftest_20260521T181135Z\atlas_graph_search_selftest.md`
- seed p95: `116 ms`
- raw-profile p95: `3,508 ms`

Interpretation:

- Correctness is now better for canonical venue/org profiles.
- Performance is not final for public deployment.
- `atlas_serving.sqlite` remains the next hard requirement.

## Current Local Runtime Snapshot

As of 2026-05-22 02:12 CST:

- Local URL: `http://127.0.0.1:18987/atlas/graph`
- Local server PID observed after restart: `17400`
- Backing DB env used for restart: `C:\code\githubstar\wechathtmldownload\tools\stage7_rewrite\reports\atlas_local_sqlite_db_138102_20260521\atlas.sqlite`
- This is local-only, not remote deployed state.

## Open Questions

- Which exact DJ aliases should be manually seeded first for high-value nodes?
- Which venues need curated alias packs beyond automatic boundary matching?
- Which review-candidate repair rows should enter the first private review workbench?
- Whether SQLite FTS5 ranking is good enough after `search_document`, or Meilisearch is worth adding.
- Which graph renderer should replace or supplement the current `3d-force-graph` experience for truly polished public UX.

## Next Best Entry

Start from:

1. `docs\ATLAS_HIGH_PERFORMANCE_DATABASE_ARCHITECTURE_20260522.md`
2. `reports\atlas_dj_low_cost_repair_sidecar_20260522\summary.md`
3. `reports\atlas_source_url_recovery_20260522\summary.md`
4. `reports\atlas_event_time_normalized_sidecar_20260522\summary.md`
5. `services\weekly_activity_cloudrun\src\stage7AtlasSqliteStore.mjs`

Immediate implementation target:

Build the first report-only `atlas_serving.sqlite` materializer that consumes raw `atlas.sqlite` plus the three sidecars and outputs canonical DJ/venue/event/relation tables. Do this locally first, with tests and self-test probes. Do not deploy until the serving artifact proves search/profile/graph-window latency.

## OpenHuman Import Status

- imported: no
- reason: this savepoint was written to project docs only. No OpenHuman import was requested in this turn.

## HTML Companion

- html_path: `docs\ATLAS_DJ_GRAPH_SAVEPOINT_AND_PLAN_20260522_COMPANION.html`
- role: human-readable companion generated from this Markdown savepoint
- canonical truth: this Markdown file remains the canonical SSOT
