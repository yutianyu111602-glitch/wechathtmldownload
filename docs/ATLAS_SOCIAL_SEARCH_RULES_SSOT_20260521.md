# Atlas 后半段社交媒体搜索算法与规则 SSOT

Updated: 2026-05-22 10:44 CST

Scope: **中国地下电子音乐图鉴 / Atlas 后半段社交媒体与外部身份搜索**。本文件是当前线程的单一口径入口，专门约束 Public Search 之后的 Post-Filter、HTTP Fast、Layer D 内容证据、OpenCLI、Maigret、Camofox、规则裁决、LLM 裁决和入图前门禁。

## 1. 当前结论

- 当前主线是 `246,024` entity keys 全量 public-search raw telemetry -> Post-Filter -> 内容/社交证据补齐 -> 规则和 LLM 裁决 -> 人工 gate -> staged graph promote。
- 旧的 2026-05-14 至 2026-05-21 P1 social/OpenCLI/Maigret 16/47/100 行链路不再是当前主执行队列；它们是算法规则、回归样本和安全边界证据。
- 任何 raw search row、snippet、URL、Maigret claimed profile、OpenCLI metadata、Layer D content span 都不是 graph identity proof。它们只能进入 review/adjudication queue。
- `accepted_for_graph`、`identity_proof`、`graph_write_allowed` 在人工明确验收前必须保持 `false`；accepted edge output 继续保持空。

Latest checked gate snapshot at `2026-05-22T10:08:28+08:00`:

- public-search status: `COMPLETE`
- progress: `246,024 / 246,024`, `100.0%`
- completion basis: `unique_entity_search_id`
- missing unique entity_search_ids: `0`
- duplicate queue entity_search_id rows: `9`; duplicate review entity_search_id rows: `5`
- full Post-Filter: complete at `2026-05-22T10:36:47+08:00`
- reduced review queue: `27`; filtered candidates: `349`; quarantine: `245,653`

2026-05-22 10:37 completion and Post-Filter closeout:

- Closeout report: `reports\ATLAS_PUBLIC_SEARCH_COMPLETION_AND_POST_FILTER_CLOSEOUT_20260522.md`.
- Public-search status is `COMPLETE`; processed `246,024 / 246,024`, remaining `0`, progress `100.0%`.
- The final apparent 4-row blocker was duplicate queue rows, not missing work: queue rows `246,024`, review rows `246,020`, unique queue ids `246,015`, unique review ids `246,015`, missing unique ids `0`.
- The stale pre-gate Post-Filter output from `2026-05-22T07:22:02+08:00` was replaced by post-completion output generated at `2026-05-22T10:36:47+08:00`.
- Full Post-Filter result: selected review rows `246,020`, scoreable review rows `12,284`, audit rows `246,020`, filtered candidates `349`, review queue `27`, quarantine `245,653`, discovery telemetry `18`.
- Noisy-name gate passed: `TAG`, `house`, `DADA`, `CISCO`, `Watermelon`, and `All` had `0` review-queue hits.
- Reduced-queue Layer D dry-run wrote `20` report-only content rows from the first `20 / 27` review rows; `accepted_for_graph=0`, `identity_proof=true` hits `0`, and `graph_write_allowed=true` hits `0`.
- Decision: Task 1 and full report-only Task 2 are complete. Next safe step is human review or separately authorized bounded content fetch over the 27-row queue; graph entry remains blocked until human gate.

2026-05-22 07:34 incident recovery:

- Previous status was `PAUSED_STOP_FILE` at `2026-05-22T01:50:01+08:00`, old PID `108336` was no longer alive, processed `223,552 / 246,024`, remaining `22,472`, prior slices `447`, `last_slice.error_count=0`.
- Current `STOP_ATLAS_ENTITY_PUBLIC_SEARCH` file is absent.
- Same resumable full-slices runner was restarted from existing checkpoint in default resume mode; no scratch restart occurred.
- New PID is `70060`; status is back to `RUNNING`; original stderr remained `0`; new resume stderr is `0`.

2026-05-21 17:25 open-source social toolchain refresh:

- Report: `reports\ATLAS_OPEN_SOURCE_TOOLCHAIN_REFRESH_20260521.md`.
- OpenCLI source and npm runtime are refreshed; global runtime is `1.8.0`, `opencli doctor` OK with browser profile `ejk3c3qe`.
- Maigret source mirror is refreshed; Docker `soxoj/maigret:latest` was pulled and `maigret-web-15051` was rebuilt on image `sha256:5c8f7bf28451ed555b86e0616af0b591c6b23c46216f40081e3c575c4573bdb9`; HTTP `200` on `127.0.0.1:15051`.
- Scrapling source is refreshed; runtime is now isolated in `C:\Users\pc\.venvs\atlas-scrapling` with wrapper `C:\Users\pc\bin\scrapling.cmd`; `scrapling extract get https://example.com ... --ai-targeted` passed.
- Lightpanda source mirror is refreshed; current runtime wrapper still smokes with `lightpanda fetch --dump markdown https://example.com`.
- Camofox-browser upstream has no newer commit; active local runtime keeps existing Windows fixes and health `127.0.0.1:9377/health` returns OK.
- User has explicitly authorized browser account-state use for this Atlas thread. The rule is now: bounded OpenCLI/Camofox browser-session reads are allowed for public profile/outlink extraction, but cookie/token values must not be exported, printed, persisted, or copied into reports; browser credential stores must not be read; account mutation remains forbidden.
- Current public-search status during this refresh: `RUNNING`, PID `108336`, `148,552 / 246,024`, `60.3811%`, `297` slices; full Post-Filter remains blocked until completion.

2026-05-21 15:00 doc/code/plan sync audit:

- Audit report: `reports\ATLAS_DOC_CODE_PLAN_SYNC_AUDIT_20260521.md`.
- Latest checked public-search gate: `COMPLETE`, `246,024 / 246,024`, `100.0%`, generated `2026-05-22T10:08:28+08:00`; completion is based on unique `entity_search_id` coverage with `0` missing unique ids.
- Traversed Markdown surface: `docs` 556, `reports` 99, `tools\stage7_rewrite` 14,867. The Stage7 count is mostly historical run/report evidence and must not be treated as current planning authority.
- Code facts checked: public-search, Post-Filter, Layer D, HTTP Fast, OpenCLI, Maigret, source-context decision, rule adjudication, LLM dual-pass, and promotion-readiness scripts all remain report-first behind graph-write gates.
- Current unified read order is now: `docs\current-runtime.md` -> this file -> `reports\ATLAS_FULL_PRODUCTION_FINAL_GOALS_STATUS_20260521.md` -> `docs\superpowers\plans\2026-05-21-atlas-full-production-final-goals.md` -> whole-Atlas authority docs -> Stage7 overlay.

2026-05-21 15:15 next-gate resilience:

- Report: `reports\ATLAS_NEXT_GATE_RESILIENCE_TEST_20260521.md`.
- Fixed `validate_graph_promotion_readiness.py` so missing default historical evidence reports become a structured `graph_promotion_blocked_missing_inputs` report instead of a `FileNotFoundError` crash.
- Added regression test `test_run_reports_missing_default_inputs_without_crashing`.
- Verification: promotion-readiness tests `8 passed`; Atlas next-gate matrix `67 passed`; `py_compile` passed for Post-Filter, Layer D, adjudication, LLM, and promotion-readiness scripts.
- Partial report-only preflight over `5,000` current raw review rows produced `1` review row and a Layer D dry-run content row with `accepted_for_graph=0`.
- This does not change graph-entry policy: promotion remains blocked until full public-search completion, reduced-queue evidence review, human acceptance, and explicit staged promotion authorization.

## 2. 读序与文档生命周期

### Current Authority

1. `docs\ATLAS_SOCIAL_SEARCH_RULES_SSOT_20260521.md` — this file; current algorithm/rule SSOT for the Atlas social-search back half.
2. `docs\current-runtime.md` — current runtime gate, process status, and latest verification.
3. `reports\ATLAS_SUBSEQUENT_SEARCH_EXECUTION_STATUS_20260521.md` — focused execution checkpoint for public-search completion, full Post-Filter closeout, and S4 readiness.
4. `tools\stage7_rewrite\SSOT.md` and `tools\stage7_rewrite\STAGE7_SSOT_20260514.md` — Stage7 overlay and durable read order.

### Active Design Inputs

- `reports\ATLAS_SUBSEQUENT_SEARCH_DEEP_RESEARCH_20260521.md` — current synthesis, but runtime counts inside older sections are snapshots.
- `reports\ATLAS_POST_OPEN_SOURCE_SEARCH_PLAN_20260521.md` — open-source stack design input, superseded by this SSOT for current execution rules.
- `reports\ATLAS_ENTITY_PUBLIC_SEARCH_POST_FILTER_PLAN_20260521.md` — Post-Filter design input, superseded by code and this SSOT for current execution status.
- `reports\ATLAS_ENTITY_PUBLIC_SEARCH_POST_FILTER_IMPLEMENTATION_20260521.md` — Post-Filter implementation evidence.
- `reports\ATLAS_LAYER_D_CONTENT_EVIDENCE_IMPLEMENTATION_20260521.md` — Layer D report-only content evidence runner evidence.
- `reports\ATLAS_PREFIX_POST_FILTER_EXPERIMENT_20260521.md` — prefix-based multi-threshold experiment and Layer D probe while public-search is still running.
- `reports\ATLAS_NEXT_GATE_RESILIENCE_TEST_20260521.md` — report-only next-gate resilience pass, including promotion-readiness missing-input hardening and partial Post-Filter / Layer D dry-runs.
- `reports\ATLAS_OPEN_SOURCE_TOOLCHAIN_REFRESH_20260521.md` — current GitHub/runtime refresh evidence for OpenCLI, Maigret, Camofox, Scrapling, and Lightpanda.
- `reports\ATLAS_PUBLIC_SEARCH_COMPLETION_AND_POST_FILTER_CLOSEOUT_20260522.md` — current completion evidence for public-search, full Post-Filter, noisy-name gate, Layer D dry-run, and graph-entry guard checks.
- `reports\ATLAS_LLM_ADJUDICATION_PLAN_20260521.md` and `reports\ATLAS_LLM_ADJUDICATION_FULL_REPORT_20260521.md` — LLM dual-pass design and mock-test evidence.
- `reports\ATLAS_OPEN_SOURCE_STACK_PHASE1_EXECUTION_20260521.md` — 16-row five-tool execution regression evidence; not the full-run queue.

### Historical / Regression Evidence

- `tools\stage7_rewrite\NETWORK_ENTITY_SEARCH_METHOD_AUDIT_20260517.md`
- `tools\stage7_rewrite\OPENCLI_EXTERNAL_EVIDENCE_PLAN_20260516.md`
- `tools\stage7_rewrite\MAIGRET_INTEGRATION_PLAN_20260510.md`
- `tools\stage7_rewrite\MAIGRET_CAMOFOX_COMBO_20260510.md`
- `tools\stage7_rewrite\CAMOFOX_INTEGRATION_PLAN_20260510.md`
- `tools\stage7_rewrite\reports\p1_*`, `graph_external_*`, `external_identity_*`, `social_identity_*`

These remain useful for examples, tests, and safety decisions. Do not resume them as production execution lanes unless this SSOT or a newer current authority promotes them.

## 3. Code Entry Points

### Current Mainline

- Query/raw run: `tools\stage7_rewrite\scripts\run_atlas_entity_public_search.py`
- Slice runner: `tools\stage7_rewrite\scripts\run_atlas_entity_public_search_full_slices.py`
- Post-Filter rules: `tools\stage7_rewrite\config\atlas_entity_public_search_post_filter_rules.json`
- Post-Filter builder: `tools\stage7_rewrite\scripts\build_atlas_entity_public_search_post_filter_queue.py`
- Layer D content evidence: `tools\stage7_rewrite\scripts\fetch_atlas_entity_public_search_content_evidence.py`
- LLM dual pass: `tools\stage7_rewrite\scripts\llm_adjudicate_identity.py`

### Tool Stack Adapters

- HTTP Fast: `tools\stage7_rewrite\scripts\run_graph_external_evidence_http_fast.py`
- OpenCLI profile metadata: `tools\stage7_rewrite\scripts\opencli_social_profile_evidence.py`
- Maigret seed/candidates: `tools\stage7_rewrite\scripts\build_graph_maigret_candidates_from_seed_queue.py`
- Maigret canary/recovery/validation: `tools\stage7_rewrite\scripts\run_maigret_http_canary.py`, `recover_maigret_web_container_reports.py`, `validate_maigret_source_hits.py`
- Phase 1 adapters: `build_atlas_open_source_phase1_seed_queue.py`, `build_atlas_open_source_phase1_review_queue.py`
- Source-context decision: `recover_external_identity_source_context.py`, `build_external_identity_source_context_decision_packet.py`
- Strict rule adjudication: `adjudicate_graph_external_identity_queue.py`

### Promotion Code Is Not Current Execution

- `neo4j_p1_social_staging_writer.py`
- `build_identity_neo4j_staging_gate_packet.py`
- `build_social_identity_acceptance_gate_packet.py`

These stay behind human acceptance and explicit staging/promote authorization.

## 4. Current Algorithm

### Stage A: Query

`build_queries()` uses profile/audio/context/city variants:

- `"{name}" (site:ra.co OR site:residentadvisor.net OR site:linktr.ee OR site:instagram.com)`
- `"{name}" (site:soundcloud.com OR site:bandcamp.com)`
- `"{name}" ("electronic music" OR "dj" OR "techno" OR "club" OR "label")`
- `"{name}" "{sample_city}" ("electronic music" OR "dj" OR "club")`

For the current full run, one query per entity means only the high-precision profile-site variant is used.

### Stage B: Post-Filter

Post-Filter is the mandatory first gate after raw search completion:

- `filtered_candidate` threshold: `35`
- `review_queue` threshold: `45`
- output lanes: `review_queue`, `filtered_candidates`, `discovery_telemetry`, `quarantine`, `audit`
- known bad terms such as `TAG`, `house`, `DADA`, `CISCO`, `Watermelon`, `All`, `GAS`, `Disco` must not enter `review_queue`
- generic short Latin names can only survive if strong music/source signals override the generic penalty

2026-05-21 prefix experiment result:

- First `50,000` review rows confirm the baseline `35 / 45` thresholds are the best current default.
- High-recall `25 / 40` produced more filtered candidates (`662` vs `182`) without adding review-queue rows.
- Strict `40 / 55` dropped one useful review row.
- Bad-name regression selected `75` known bad rows and produced `0` review rows; all were quarantined.

Domain policy:

- T1 music direct: RA, SoundCloud, Bandcamp, Mixcloud, Beatport, Discogs, music platforms
- T2 social/profile: Instagram, Linktree, YouTube, Bilibili, Douban, Weibo, X/Twitter, Facebook
- T3 China music/media: Dada-related domains and local music/media sources
- T4 reference: Wikipedia/Baike/Britannica only as context, not identity proof
- deny: dictionary/game/property/medical/enterprise support domains and matching deny paths

### Stage C: Content Evidence

Layer D runs only after Post-Filter has reduced the queue.

Allowed modes:

- `dry-run` for shape verification
- `http` for public URL text extraction
- `scrapling-get` for explicit Scrapling CLI extraction using `--ai-targeted`

Required row facts:

- sanitized public URL
- fetch status and fetcher
- subject term matches
- music context matches
- evidence spans
- `needs_llm_adjudication`
- all graph-write flags false

2026-05-21 Layer D prefix probe:

- Dry-run over `10` baseline prefix review rows succeeded with `accepted_for_graph=0`.
- HTTP fetch over the same `10` rows fetched `4`, produced `http_403` for `6`, and found `3` LLM-eligible content rows.
- HTTP 403 is not negative evidence; RA/Discogs blocked rows should route to a bounded fallback.
- Scrapling CLI probe returned `fetcher_missing`, so Scrapling must be activated before using the `scrapling-get` path.
- The content runner now converts HTTP errors into report-only rows instead of crashing the batch.

### Stage D: OpenCLI / Maigret / Camofox

Default order:

1. HTTP Fast for reachability
2. Layer D public content extraction for evidence spans
3. OpenCLI only for bounded profile metadata where a browser-visible public page is needed
4. Maigret only for Latin handle breadth discovery, never as identity proof
5. Camofox only as an anti-bot fallback when HTTP/Layer D/OpenCLI cannot obtain public page evidence

Current authorization permits **bounded logged-in browser-session reads** through OpenCLI/Camofox for public profile/outlink extraction. This does not permit exporting, printing, persisting, or copying cookie/token values; it does not permit reading browser credential stores; it does not permit account mutation. Browser-session evidence remains report-only until strict rule, LLM, and human gates accept it.

Maigret current service evidence uses `127.0.0.1:15051`; historical `5050` references are stale unless a current health check says otherwise.

### Stage E: Rule And LLM Adjudication

Rule adjudication buckets rows into:

- `opencli_profile_content_subject_match_needs_manual_acceptance`
- `opencli_profile_content_needs_subject_match`
- `strong_url_profile_candidate_needs_content_extract`
- `medium_url_profile_candidate_needs_content_extract`
- `reachable_music_profile_needs_subject_match`
- `maigret_candidate_only_needs_source_backed_review`
- `context_missing_subject`
- `weak_or_unclassified_identity_evidence`

LLM dual-pass is eligible only when direct profile/content evidence exists. Maigret-only, medium URL-only, context-missing, and weak rows are excluded until more source text exists.

LLM acceptance still does not equal graph promotion. Human acceptance and a separate staging/promote gate remain required.

## 5. Current Execution Gate

Do not run full Post-Filter until:

- `entity_public_search_full_run_status.json` has `status == "COMPLETE"`
- `processed_review_rows == queue_entity_keys`
- accepted graph output is still empty
- slice log has no unresolved fatal errors

After completion:

1. run full Post-Filter with quarantine emitted
2. verify known-bad names are quarantined
3. run Layer D dry-run on a small sample
4. run Layer D `http` / `scrapling-get` only on reduced review queue slices
5. join HTTP/OpenCLI/Maigret/Layer D evidence into review queue
6. run strict rule adjudication
7. run LLM dual-pass only for eligible rows
8. hand <=50 top rows to human gate
9. promote only explicitly accepted edges into staging

## 6. Verification Set

Minimum local verification for this thread:

```powershell
python -m pytest tests\test_fetch_atlas_entity_public_search_content_evidence.py tests\test_build_atlas_entity_public_search_post_filter_queue.py tests\test_run_atlas_entity_public_search.py tests\test_build_atlas_open_source_phase1_review_queue.py tests\test_adjudicate_graph_external_identity_queue.py tests\test_llm_adjudicate_identity.py -q
python -m py_compile scripts\fetch_atlas_entity_public_search_content_evidence.py scripts\build_atlas_entity_public_search_post_filter_queue.py scripts\run_atlas_entity_public_search.py scripts\build_atlas_open_source_phase1_review_queue.py scripts\adjudicate_graph_external_identity_queue.py scripts\llm_adjudicate_identity.py
```

Current recent verification:

- Atlas subsequent-search targeted tests: `37 passed`
- Prefix Post-Filter / Layer D targeted tests after HTTP error fix: `34 passed`
- Layer D / Post-Filter / LLM `py_compile`: passed
- Layer D canary dry-run: `12` input rows, `3` selected, `3` `dry_run` rows, `accepted_for_graph=0`
- Stage7 safe handoff verify: `PASS`; Python targeted tests `353 passed`; CloudRun Stage7 atlas API tests `38 passed / 0 failed`

## 7. Red Lines

- Do not kill or restart the active public-search PID during the full public-search run; current checked PID is `70060`.
- Do not run OpenCLI, Maigret, Camofox, or Scrapling over raw 246k telemetry.
- Do not treat SearXNG snippets, Maigret hits, or OpenCLI metadata as identity proof.
- Do not export, print, persist, or copy cookies/tokens; do not read browser credential stores; do not mutate accounts.
- Do not write Neo4j, Qdrant, production SQLite, mem0, or agentmemory from this lane.
- Do not deploy CloudRun or upload/review the mini-program from this thread.
- Do not scan `D:\`, `D:\DDownload`, or `D:\aidata`.
- Do not use local `9router`.
