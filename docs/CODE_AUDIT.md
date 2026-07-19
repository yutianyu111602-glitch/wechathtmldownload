# Code Audit

Updated: 2026-07-19

## Scope

Audited current code structure and the 93k Stage7 recovery path without reading private runtime secrets.

## 2026-07-19 HUAIDJ weekly/miniprogram systemic audit

Scope: the dirty integration candidate at
`F:\DevData\HuaidjRuntime\build\weekly-visibility-20260719`, plus read-only
public weekly API reproduction. Secrets, Sanji credential tables, production
write paths, review submission, and serving-pointer mutation were excluded.

### Root cause proven

The production symptom is a three-layer contract split, not a visual-only bug:

1. the old mini-program reduced `本周末` to the first Friday and sent one
   `selectedDate`;
2. the old `/current` accepted exact `date` but ignored `dateStart/dateEnd`;
3. the old `/cities` returned package-wide counts without scope/date/generation
   identity, while client pagination/cache could silently retain only a first
   page.

On 2026-07-19 the public API returned package `626`, current `64`, Shanghai
current `13`, Shanghai exact `2026-07-24` `3`, and Shanghai cities count `131`
for both exact and weekend-range queries. See
`HUAIDJ_MINIPROGRAM_LOADING_ROOT_CAUSE_20260719.md` for the query table.

### Candidate repair shape

- Shared Asia/Shanghai date visibility exists across mini-program, CloudBase
  sync, CloudRun, and package generation. Weekend state is an explicit
  Friday-Sunday range; long ranges use interval intersection rather than a
  capped list of enumerated days.
- Client current loading validates every page, total, unique ID, cursor and
  generation before atomically replacing the last-good cache. Facets are used
  only when their generation/scope/item count/buckets match the same visible
  set; otherwise the client recomputes them from that set.
- CloudBase hot sync stages and validates a new generation before the config
  pointer switch. Package stamping and route generation have contained-path
  and public-projection gates.
- The maintained daily wrapper uses an OS-backed lease; stale metadata age is
  not authority to delete/steal a live run. Hermes installer output binds repo,
  Python and report root and is designed for dry-run/apply/idempotence audit.
- Sound ingress/evidence paths separate private evidence from public response
  fields and add first-write/concurrency/error-path coverage.
- Atlas graph/index/neighborhood artifacts share a snapshot-derived
  `datasetId`; missing or mismatched IDs fail closed. The triplet builder writes
  only a new external candidate and hashes inputs/source before and after.

### Remaining release risks and gates

| Risk | Required gate before release claim |
| --- | --- |
| A late edit reintroduces a local path, private source map, file URL, or secret into a public package/response | final tracked-secret and public-artifact leak scans plus real package validation |
| Pagination/facet tests pass on fixtures but DevTools loads a stale cache or wrong static package | fresh uniquely named eight-scenario DevTools suite bound to one package fingerprint |
| Candidate tests pass but runtime still launches an older checkout | clean commit/push, correctly named detached release, installer second dry-run no-change, contract audit, real Gateway child command |
| Sanji database is fresh only for the prior 96-hour lane | new Desktop-driven 744-hour summary, frozen snapshot, missing-HTML digest `unresolved=0` before paid models |
| Local package is correct but online/CloudBase/client generations diverge | CloudRun full pagination and facet readback, then CloudBase same-`syncId` readback |
| Development upload is mistaken for user-visible repair | separate upload, review-submitted, approved, public-release and public-device evidence |
| Atlas candidate generation is mistaken for promotion | SQLite/digest/identity candidate evidence plus explicit unchanged/promotion pointer report |

Intermediate test runs are useful debugging evidence but are not final
acceptance after concurrent edits. The final Node, Python, PowerShell, leak-scan
and real-DevTools suites must be rerun from the commit that becomes the release.
No 2026-07-19 CloudRun deploy, CloudBase hot sync, mini-program upload/review/
public release, Hermes cutover, 744-hour run, or Atlas serving promotion is
claimed by this audit.

2026-05-27 atlas final local candidate preflight and T6 year-context review:

- Added `tools\stage7_rewrite\scripts\build_atlas_t6_time_title_year_context_review_packet.py` and `tools\stage7_rewrite\tests\test_build_atlas_t6_time_title_year_context_review_packet.py`.
- Output packets: `reports\ATLAS_T6_TIME_TITLE_YEAR_CONTEXT_REVIEW_20260527.md` and `reports\ATLAS_T5_T6_TIME_CITY_YEAR_SPAN_FINAL_CANDIDATE_PREFLIGHT_20260527.md`; final preflight output `reports\atlas_serving_time_city_year_span_final_candidate_preflight_20260527_2145\promotion_preflight.json`.
- Counts: final candidate/baseline counts match for performance_event `508049`, dj_profile `53555`, dj_event `1285827`, relation `701396`, search docs `590927`, graph windows `53555`, activity `196/2181`; graph-window gap `0`; forbidden schema/value and hard-noise hits `0`. T6 year-context input/review/ready/blocked `1366/1366/0/1366`, split source-artifact `443`, weekday-year review `647`, conflict/ambiguous `276`, multi-event guide/news `41`, leak hits `0/0/0`.
- LLM audit: a year token is insufficient when multiple month/day candidates exist; the first focused test caught over-acceptance and the builder now blocks those rows for source-artifact/manual review.
- Boundary: this slice was local/report-only. It did not open/write source/raw DB, mutate selected serving SQLite, write graph/vector/production/public pointer, upload huaidj.club, deploy CloudRun/VPS, upload/review mini-program, write memory, read credentials, call network/OCR/model, use 9router, use destructive Git, or scan D roots.
- Focused verification passed: `py_compile`; focused year-context pytest `4 passed`; combined focused T6/T5 pytest `16 passed`; final promotion preflight parsed and returned `promotion_preflight_passed_local_only`; stale preflight process check found no matching process.

2026-05-27 atlas T6/T5 span split recovery, source/raw write, serving overlay, and local API/package preflight:

- Added `tools\stage7_rewrite\scripts\build_atlas_t6_time_title_span_split_review_packet.py` and `tools\stage7_rewrite\tests\test_build_atlas_t6_time_title_span_split_review_packet.py`.
- Output packets: `reports\ATLAS_T6_TIME_TITLE_SPAN_SPLIT_REVIEW_20260527.md`, `reports\ATLAS_T6_TIME_TITLE_SPAN_SPLIT_READBACK_GATE_20260527.md`, `reports\ATLAS_T5_TIME_ISO_SPAN_SPLIT_WRITE_PREFLIGHT_PACKET_20260527.md`, `reports\ATLAS_T5_TIME_ISO_SPAN_SPLIT_WRITE_EXECUTION_GATE_20260527.md`, `reports\ATLAS_T5_SERVING_TIME_OVERLAY_SPAN_SPLIT_CANDIDATE_20260527.md`, `reports\ATLAS_T5_SERVING_TIME_OVERLAY_SPAN_SPLIT_SEARCH_GRAPH_SMOKE_20260527.md`, `reports\ATLAS_T5_SERVING_TIME_OVERLAY_SPAN_SPLIT_SEARCH_DATE_REFRESH_GATE_20260527.md`, and `reports\ATLAS_T5_SERVING_TIME_OVERLAY_SPAN_SPLIT_LOCAL_API_PACKAGE_PREFLIGHT_20260527.md`.
- Counts: span/split review input/review/ready/blocked `16/16/14/2`; selected-serving readback ready/blocked `14/0`; source/raw preflight mapped/blocked readback groups `8/6`; committed source/raw `events.time_iso` rows `51` with postwrite match `51/51`; serving changed rows `395` split performance_event/dj_event `47/348`; starts_at gaps improved performance_event `154,030->153,983` and dj_event `429,924->429,576`; search-date refresh rows `47` with postwrite search text/FTS matches `47/47`; API/browser checks `25/25` and `5/5`; package context ready rows `1`; sidecars copied `2`; leak hits `0/0/0`.
- LLM audit: the first regression caught a real English month parsing bug (`3 february 2022` must become `2022-02-03`, not `2022-03-02`). The gate now treats source-title and first-source-time evidence conservatively, keeps multi-event guide/news rows blocked, and avoids turning every span/range mention into a single event date.
- Boundary: source/raw DB mutation was limited to `events.time_iso` `51` rows inside the confirmed writer. Selected serving SQLite was not mutated. Report-local candidate DB copies were mutated only for `starts_at`, event `search_document.search_text`, and FTS. No graph/vector/production SQLite/public pointer, huaidj.club upload, CloudRun/VPS deploy, mini-program upload/review, memory, network/OCR/model call, credential read, 9router, destructive Git, or D-root action occurred.
- Focused verification passed: `py_compile`; focused span/split pytest `3 passed`; combined time-overlay pytest `19 passed`; `node --check services\weekly_activity_cloudrun\scripts\atlasServingLocalSmoke.mjs`; local API/browser smoke `ok=true`; JSON parse `11` files OK; structured leak scan zero and raw URL/secret/absolute-path grep passed.

2026-05-27 atlas T5 time year-span local API/package preflight:

- Added `tools\stage7_rewrite\scripts\build_atlas_t5_serving_time_overlay_local_api_package_preflight.py` and `tools\stage7_rewrite\tests\test_build_atlas_t5_serving_time_overlay_local_api_package_preflight.py`.
- Output packet: `reports\ATLAS_T5_SERVING_TIME_OVERLAY_YEAR_SPAN_LOCAL_API_PACKAGE_PREFLIGHT_20260527.md`; machine outputs under `tools\stage7_rewrite\reports\atlas_t5_serving_time_overlay_year_span_local_api_package_preflight_20260527`, including `serving_time_overlay_local_api_package_preflight_summary.json` and `serving_time_overlay_local_api_package_contract.json`.
- Package context: `reports\atlas_serving_time_year_span_overlay_cloudrun_context_20260527_1815\atlas_serving_sqlite_cloudrun_context.json`, prepared from candidate DB `reports\atlas_serving_time_overlay_year_span_search_date_refresh_candidate_20260527_1804\atlas_serving.sqlite` and verified sidecars.
- Counts: API/browser checks `24/24` and `5/5`; search-document update rows `380`; postwrite search text/FTS date matches `380/380`; input changed rows `2703`; candidate DB alignment rows `1`; package context ready rows `1`; sidecars copied `2`; table-count drift `0`; leak hits `0/0/0`.
- LLM audit: after the source/raw time write and report-local search refresh, SQL/readback evidence was no longer enough; the candidate needed a consumer/package contract tying the refreshed SQLite copy to local HTTP, browser, search-date refresh, and CloudRun context sidecar copy evidence. Public upload remains closed.
- Boundary: local package/API contract only; no source/raw DB open in this slice, selected serving mutation/rebuild, graph/vector/production/public pointer, huaidj.club upload, CloudRun/VPS deploy, mini-program, memory, network/OCR/model call, credential read, 9router, destructive Git, or D-root action occurred.
- Focused verification passed: `py_compile`; focused preflight pytest `3 passed`; combined time-overlay/package pytest `11 passed` with `PYTHONPATH=.`; `node --check`; JSON parse `3` files OK; strict leak grep returned no hits.

2026-05-27 atlas T6/T5 time year-span recovery, source/raw write, and serving overlay:

- Added `tools\stage7_rewrite\scripts\build_atlas_t6_time_title_year_span_recovery_packet.py` and `tools\stage7_rewrite\tests\test_build_atlas_t6_time_title_year_span_recovery_packet.py`.
- Updated `tools\stage7_rewrite\scripts\build_atlas_t5_serving_time_overlay_candidate.py` with `--report` support so cumulative report-local candidates can emit distinct reports.
- Output packets: `reports\ATLAS_T6_TIME_TITLE_YEAR_SPAN_RECOVERY_20260527.md`, `reports\ATLAS_T6_TIME_TITLE_YEAR_SPAN_READBACK_GATE_20260527.md`, `reports\ATLAS_T5_TIME_ISO_YEAR_SPAN_WRITE_PREFLIGHT_PACKET_20260527.md`, `reports\ATLAS_T5_TIME_ISO_YEAR_SPAN_WRITE_EXECUTION_GATE_20260527.md`, `reports\ATLAS_T5_SERVING_TIME_OVERLAY_YEAR_SPAN_CANDIDATE_20260527.md`, `reports\ATLAS_T5_SERVING_TIME_OVERLAY_YEAR_SPAN_SEARCH_GRAPH_SMOKE_20260527.md`, and `reports\ATLAS_T5_SERVING_TIME_OVERLAY_YEAR_SPAN_SEARCH_DATE_REFRESH_GATE_20260527.md`.
- Counts: recovery ready rows `64` split year-month-day/span-start `55/9`; selected-serving readback ready/blocked `64/0`; source/raw committed `events.time_iso` rows `242` with postwrite match `242/242`; serving candidate changed rows `2,703` split performance_event/dj_event `380/2,323`; starts_at gaps improved performance_event `154,410->154,030` and dj_event `432,247->429,924`; search-date refresh rows `380` with postwrite search text/FTS matches `380/380`; final local API/browser smoke `ok=true`; leak hits `0/0/0`.
- LLM audit: the high-value blocker was no longer public packaging but unconsumed deterministic time evidence inside the month/day-year and span/range queues. The new recovery gate accepts only single-year + single-month-day or deterministic range-start evidence, rejects weekday mismatches and split spans, then routes every write through existing readback/prewrite/rollback/postwrite gates.
- Boundary: source/raw mutation was limited to confirmed `events.time_iso` rows. Selected serving SQLite was not mutated. Report-local candidate DB copies were mutated only for `starts_at`, event `search_document.search_text`, and FTS. No graph/vector/production SQLite/public pointer, huaidj.club upload, CloudRun/VPS deploy, mini-program upload/review, memory, network/OCR/model call, credential read, 9router, destructive Git, or D-root action occurred.
- Focused verification passed: py_compile for changed/reused scripts; time/year-span/time-ISO/serving pytest `23 passed`; `node --check services\weekly_activity_cloudrun\scripts\atlasServingLocalSmoke.mjs`; local API/browser smoke exited `0`; JSON parse check `9` files OK; strict URL/key/path/source grep returned no hits.

2026-05-27 atlas entity-merge second-pass local API/package preflight:

- Added `tools\stage7_rewrite\scripts\build_atlas_entity_merge_secondpass_local_api_package_preflight.py` and `tools\stage7_rewrite\tests\test_build_atlas_entity_merge_secondpass_local_api_package_preflight.py`.
- Output packet: `reports\ATLAS_ENTITY_MERGE_SECONDPASS_LOCAL_API_PACKAGE_PREFLIGHT_20260527.md`; machine outputs under `tools\stage7_rewrite\reports\atlas_entity_merge_secondpass_local_api_package_preflight_20260527`, including `entity_merge_secondpass_local_api_package_preflight_summary.json` and `entity_merge_secondpass_local_api_package_contract.json`.
- Counts: API checks `24/24`; browser checks `5/5`; mobile entity checks `6/6`; known cases `3/3`; queue/latest decisions `28,853/28,853`; missing decisions `0`; final merge groups / merged subjects `7,094/24,609`; review/split rows `9,082/7,424`; duplicate subject/member-count/forbidden-hit counts `0/0/0`; package sidecars copied `2/2`; leak hits `0/0/0`.
- LLM audit: the accepted second-pass DeepSeek Pro sidecar was already JSONL-valid at 16:50, but public-package readiness also requires HTTP service behavior, mobile query preference for short labels such as `ALL`, bounded large-group profile aggregation, browser rendering, and local context sidecar copy proof. The new gate binds those together without promoting public state.
- Boundary: local package/API contract only; no source/raw DB open/write, selected serving mutation/rebuild, graph/vector/production/public pointer, huaidj.club upload, CloudRun/VPS deploy, mini-program, memory, network/OCR/model call, credential read, 9router, destructive Git, or D-root action occurred.
- Focused verification passed: `python -m py_compile tools\stage7_rewrite\scripts\build_atlas_entity_merge_secondpass_local_api_package_preflight.py`; focused package/context/entity-merge pytest `10 passed`; strict URL/key/path/source grep over generated report/output returned no hits.

2026-05-27 atlas T5 serving time overlay search-date refresh gate:

- Added `tools\stage7_rewrite\scripts\build_atlas_t5_serving_time_overlay_search_date_refresh_gate.py` and `tools\stage7_rewrite\tests\test_build_atlas_t5_serving_time_overlay_search_date_refresh_gate.py`.
- Output packet: `reports\ATLAS_T5_SERVING_TIME_OVERLAY_SEARCH_DATE_REFRESH_GATE_20260527.md`; machine outputs under `tools\stage7_rewrite\reports\atlas_t5_serving_time_overlay_search_date_refresh_gate_20260527`, including `serving_time_overlay_search_date_refresh_summary.json`, refreshed rows, rollback contracts, postwrite readback rows, samples, and blocked rows. Candidate DB: `reports\atlas_serving_time_overlay_search_date_refresh_candidate_20260527_1518\atlas_serving.sqlite`.
- Counts: event refresh target rows `394`; search document update rows `394`; search text changed rows `394`; postwrite search text date matches `394`; postwrite FTS date matches `394`; rollback/postwrite contracts `394/394`; table-count drift `0`; local API/browser smoke `ok=true`; generated report leak hits `0/0/0`.
- LLM audit: after the 15:00 read-only smoke, the remaining blocker was not graph/readback correctness but stale event search text/FTS. The new gate intentionally mutates only a copied report-local candidate DB, appends deterministic date tokens to affected event search documents, rebuilds FTS, and records rollback/readback evidence.
- Boundary: report-local candidate DB mutation only; no source/raw DB open/write, selected serving mutation, serving rebuild, graph/vector/production/public pointer, huaidj.club upload, CloudRun/VPS, mini-program, memory, network/OCR/model call, credential read, 9router, destructive Git, or D-root action occurred.
- Focused verification passed: `python -m py_compile tools\stage7_rewrite\scripts\build_atlas_t5_serving_time_overlay_search_date_refresh_gate.py`; focused pytest `2 passed`; combined time-overlay pytest `13 passed`; `node --check services\weekly_activity_cloudrun\scripts\atlasServingLocalSmoke.mjs` passed; local Stage7 API/browser smoke exited `0`.

2026-05-27 atlas T5 serving time overlay search/graph smoke:

- Added `tools\stage7_rewrite\scripts\build_atlas_t5_serving_time_overlay_search_graph_smoke.py` and `tools\stage7_rewrite\tests\test_build_atlas_t5_serving_time_overlay_search_graph_smoke.py`.
- Output packet: `reports\ATLAS_T5_SERVING_TIME_OVERLAY_SEARCH_GRAPH_SMOKE_20260527.md`; machine outputs under `tools\stage7_rewrite\reports\atlas_t5_serving_time_overlay_search_graph_smoke_20260527`, including `serving_time_overlay_search_graph_smoke_summary.json`, `serving_time_overlay_api_contract.json`, readback/search/graph samples, and failed rows.
- Counts: changed rows input `3333`; performance_event starts_at readback `394/394`; dj_event starts_at readback `2939/2939`; event search docs present/missing `394/0`; event search text missing date rows `349`; graph window seeds/missing seeds `292/0`; metric drift rows `0`; search-date refresh required rows `394`; local API/browser smoke `ok=true`; leak hits `0/0/0`.
- LLM audit: the report-local serving time overlay candidate already preserves table counts and improves `starts_at`, but public packaging needs a narrower search-date refresh gate because `349/394` event search texts still lack the visible date token. The new smoke therefore separates graph/readback correctness from search-index readiness instead of treating the overlay as deployable.
- Boundary: candidate serving SQLite opened read-only only; no source/raw DB open/write, selected serving mutation, serving rebuild, graph/vector/production/public pointer, huaidj.club upload, CloudRun/VPS, mini-program, memory, network/OCR/model call, credential read, 9router, destructive Git, or D-root action occurred.
- Focused verification passed: `python -m py_compile tools\stage7_rewrite\scripts\build_atlas_t5_serving_time_overlay_search_graph_smoke.py`; focused pytest `2 passed`; combined time-overlay pytest `11 passed`; targeted URL/path/secret grep over new report/output returned no hits; summary JSON parsed successfully.

2026-05-27 atlas T5 time ISO write execution and serving time overlay candidate:

- Added `tools\stage7_rewrite\scripts\build_atlas_t5_time_iso_write_preflight_packet.py` and `tools\stage7_rewrite\tests\test_build_atlas_t5_time_iso_write_preflight_packet.py`.
- Added `tools\stage7_rewrite\scripts\run_atlas_t5_time_iso_write_execution_gate.py` and `tools\stage7_rewrite\tests\test_run_atlas_t5_time_iso_write_execution_gate.py`.
- Added `tools\stage7_rewrite\scripts\build_atlas_t5_serving_time_overlay_candidate.py` and `tools\stage7_rewrite\tests\test_build_atlas_t5_serving_time_overlay_candidate.py`.
- Output packets: `reports\ATLAS_T5_TIME_ISO_WRITE_PREFLIGHT_PACKET_20260527.md`, `reports\ATLAS_T5_TIME_ISO_WRITE_EXECUTION_GATE_20260527.md`, and `reports\ATLAS_T5_SERVING_TIME_OVERLAY_CANDIDATE_20260527.md`; machine outputs under `tools\stage7_rewrite\reports\atlas_t5_time_iso_write_preflight_20260527`, `tools\stage7_rewrite\reports\atlas_t5_time_iso_write_execution_gate_20260527`, and `tools\stage7_rewrite\reports\atlas_t5_serving_time_overlay_candidate_20260527`.
- Counts: preflight input/mapped/blocked readback rows `78/75/3`; raw `events.time_iso` update targets `690`; duplicate selector groups `132`; conflict groups `0`; committed source/raw rows `690`; postwrite readback/time-iso matches `690/690`; rollback contracts `690`; serving candidate mapping rows `3333`; changed `starts_at` rows `3333` split performance_event/dj_event `394/2939`; table-count drift rows `0`; starts_at gaps improved performance_event `154804->154410` and dj_event `435186->432247`; local API/browser smoke `ok=true`; leak hits `0/0/0`.
- LLM audit: source/raw `events` writes must target `time_iso`, not serving `starts_at`; serving `starts_at` is a derived read-model field. The first date matcher had a real infinite-growth bug from extending a list while iterating it, and the fixed matcher separates full-year tokens from month/day tokens so month/day-only raw rows cannot override conflicting year evidence.
- Boundary: source/raw DB mutation was limited to confirmed `events.time_iso` rows; selected serving SQLite was not mutated; the serving overlay is a report-local candidate DB under `reports\atlas_serving_time_overlay_candidate_20260527_0925`. No graph/vector/production SQLite/public pointer, huaidj.club upload, CloudRun/VPS deploy, mini-program upload/review, memory, network/OCR/model call, credential read, 9router, destructive Git, or D-root action occurred.
- Focused verification passed: py_compile for all three scripts; focused pytest `9 passed`; combined focused pytest `17 passed`; serving overlay focused pytest `14 passed`; direct source/raw readback confirmed `690` non-empty `time_iso` rows across `57` dates; local Stage7 API/browser smoke exited `0`; strict grep found only local smoke URLs/relative candidate DB paths/public DeepSeek base URL in smoke config, not keys or raw source URLs.

2026-05-27 atlas T6 time-title exact-date recovery/readback gate:

- Added `tools\stage7_rewrite\scripts\build_atlas_t6_time_title_exact_date_recovery_packet.py` and `tools\stage7_rewrite\tests\test_build_atlas_t6_time_title_exact_date_recovery_packet.py`.
- Added `tools\stage7_rewrite\scripts\build_atlas_t6_time_title_readback_gate.py` and `tools\stage7_rewrite\tests\test_build_atlas_t6_time_title_readback_gate.py`.
- Output packets: `reports\ATLAS_T6_TIME_TITLE_EXACT_DATE_RECOVERY_20260527.md` and `reports\ATLAS_T6_TIME_TITLE_READBACK_GATE_20260527.md`; machine outputs under `tools\stage7_rewrite\reports\atlas_t6_time_title_exact_date_recovery_20260527` and `tools\stage7_rewrite\reports\atlas_t6_time_title_readback_gate_20260527`.
- Counts: recovery input work orders `2000`; candidate-ready rows `78`; exact-full-date ready `75`; relative-post-date ready `2`; month-day-with-post-date ready `1`; month/day-year required `1281`; span/range review `168`; relative-date source-context `352`; ambiguous multiple-date review `13`; weak/false date-token blocked `4`; source/OCR/manual recovery `104`; readback input/readback/ready/blocked `78/78/78/0`; performance-event missing `starts_at` rows covered `412`; DJ-event missing `starts_at` rows covered `3036`; unique event IDs/DJ IDs `412/314`; leak hits `0/0/0`.
- LLM audit: weak numeric labels such as `v2.0` and `20/20` must not become date evidence; rows containing a single full date but conflicting month/day tokens in the same source group must go to ambiguity review; selected-serving readback must batch source refs because per-ref queries over `508k/1.28M` tables can time out.
- Focused verification passed: py_compile for both new scripts; recovery pytest `4 passed`; readback pytest `3 passed`; combined T6/T5 focused pytest `9 passed`; strict URL/key/path grep over new report/output returned no hits.

2026-05-27 atlas T5 serving city overlay local API package preflight:

- Added `tools\stage7_rewrite\scripts\build_atlas_t5_serving_city_overlay_local_api_package_preflight.py` and `tools\stage7_rewrite\tests\test_build_atlas_t5_serving_city_overlay_local_api_package_preflight.py`.
- Updated `services\weekly_activity_cloudrun\scripts\atlasServingLocalSmoke.mjs` to include city event searches and to treat top-level `kind: "events"` as event result rows.
- Output packet: `reports\ATLAS_T5_SERVING_CITY_OVERLAY_LOCAL_API_PACKAGE_PREFLIGHT_20260527.md`; machine outputs under `tools\stage7_rewrite\reports\atlas_t5_serving_city_overlay_local_api_package_preflight_20260527`, including `serving_city_overlay_local_api_package_preflight_summary.json` and `serving_city_overlay_local_api_package_contract.json`.
- Local smoke and package evidence: `reports\atlas_serving_city_overlay_local_api_smoke_20260527_0813\api_smoke.json`, `browser_smoke.json`, `atlas_browser_smoke.png`, `reports\atlas_serving_city_overlay_cloudrun_context_20260527_0816\atlas_serving_sqlite_cloudrun_context.json`, and local context `services\weekly_activity_cloudrun\tmp\cloudrun_deploy_context_city_overlay_20260527_0816`.
- LLM audit: the first smoke failed because the smoke script looked only for `item.type === "event"`. The API returned correct city event rows with `kind: "events"`, so the assertion was fixed and rerun.
- Counts: API checks `16/16`; browser checks `5/5`; city event searches `5`; city event result/match rows `40/40`; short-city fallback match rows `12284`; package context ready rows `1`; sidecars copied `2`; leak hits `0/0/0`; CloudRun deploy/huaidj upload/public pointer/write rows all `0`.
- Focused verification passed: `node --check services\weekly_activity_cloudrun\scripts\atlasServingLocalSmoke.mjs`; weekly CloudRun serving SQLite tests `63 passed`; passing local API smoke exit `0`; local CloudRun package context prepare exit `0`; py_compile passed; focused pytest `2 passed`; combined city overlay pytest `8 passed`; strict URL/key/path grep over new report/output returned no hits.

2026-05-27 atlas T5 serving city overlay short-city search gate and service fallback:

- Added `tools\stage7_rewrite\scripts\build_atlas_t5_serving_city_overlay_short_city_search_gate.py` and `tools\stage7_rewrite\tests\test_build_atlas_t5_serving_city_overlay_short_city_search_gate.py`.
- Updated `services\weekly_activity_cloudrun\src\stage7AtlasSqliteStore.mjs` so empty FTS results fall back to exact `search_document.city_text = ?` for public city labels and short CJK labels.
- Updated `services\weekly_activity_cloudrun\tests\stage7SqliteLocal.test.mjs` with short CJK city-search regressions.
- Output packet: `reports\ATLAS_T5_SERVING_CITY_OVERLAY_SHORT_CITY_SEARCH_GATE_20260527.md`; machine outputs under `tools\stage7_rewrite\reports\atlas_t5_serving_city_overlay_short_city_search_gate_20260527`, including `serving_city_overlay_short_city_search_gate_summary.json`, `serving_city_overlay_short_city_search_contract.json`, fallback samples, fallback status rows, and failed rows.
- LLM audit: FTS5 trigram cannot answer the `24` short CJK city terms in the overlay, so a blind FTS delta/rebuild would still miss them. Exact `city_text` fallback is narrower and safer than broad LIKE, which returned `400130` rows.
- Counts: overlay event search rows `12284`; direct city fallback match rows `12284`; direct missing/mismatch/text-missing rows `0/0/0`; FTS city-term match rows `0`; FTS short-city refresh-insufficient rows `12284`; service fallback markers passed `6/6`; leak hits `0/0/0`.
- Focused verification passed: `python -m py_compile tools\stage7_rewrite\scripts\build_atlas_t5_serving_city_overlay_short_city_search_gate.py`; focused pytest -> `2 passed`; `node --check services\weekly_activity_cloudrun\src\stage7AtlasSqliteStore.mjs`; focused Stage7 SQLite Node test -> `14 passed`; combined city overlay pytest -> `6 passed`; `npm test --prefix services\weekly_activity_cloudrun` -> `63 passed`; strict URL/key/path grep over new report/output returned no hits.

2026-05-27 atlas T5 serving city overlay search/graph smoke addition:

- Added `tools\stage7_rewrite\scripts\build_atlas_t5_serving_city_overlay_search_graph_smoke.py` and `tools\stage7_rewrite\tests\test_build_atlas_t5_serving_city_overlay_search_graph_smoke.py`.
- Output packet: `reports\ATLAS_T5_SERVING_CITY_OVERLAY_SEARCH_GRAPH_SMOKE_20260527.md`; machine outputs under `tools\stage7_rewrite\reports\atlas_t5_serving_city_overlay_search_graph_smoke_20260527`, including `serving_city_overlay_search_graph_smoke_summary.json`, `serving_city_overlay_api_contract.json`, direct search samples, graph samples, failed rows, and FTS status.
- LLM audit: the generic serving health refresh could not prove the exact 07:01 city overlay rows or express deferred FTS as a separate public-serving gate. The new script validates overlay-specific direct search readback, DJ-event graph coverage, graph-window seeds, metric drift, and FTS status.
- Counts: overlay event search rows checked `12284`; direct search city matches `12284`; direct missing/mismatch/text-missing rows `0/0/0`; graph event rows checked `12284`; DJ-event edges `38103`; unique DJs `5094`; graph window seed rows `5094`; missing graph seeds `0`; metric drift rows `0`; FTS refresh required rows `12284`; FTS city terms requiring refresh `24`; leak hits `0/0/0`.
- Self-correction: focused tests exposed repo-external temp-path false positives in the local-path leak scanner. The builder now hash-redacts repo-external paths before writing report-local outputs, while production relative paths remain readable.
- Focused verification passed: `python -m py_compile tools\stage7_rewrite\scripts\build_atlas_t5_serving_city_overlay_search_graph_smoke.py`; focused pytest -> `2 passed`; combined city smoke/overlay/preflight/write pytest -> `11 passed`; strict URL/key/path grep over new report/output returned no hits; summary JSON parsed successfully.

2026-05-27 atlas T5 city write execution and serving overlay candidate addition:

- Added `tools\stage7_rewrite\scripts\run_atlas_t5_city_write_execution_gate.py` and `tools\stage7_rewrite\tests\test_run_atlas_t5_city_write_execution_gate.py`.
- Added `tools\stage7_rewrite\scripts\build_atlas_t5_serving_city_overlay_candidate.py` and `tools\stage7_rewrite\tests\test_build_atlas_t5_serving_city_overlay_candidate.py`.
- Source/raw write output: `reports\ATLAS_T5_CITY_WRITE_EXECUTION_GATE_20260527.md`; machine outputs under `tools\stage7_rewrite\reports\atlas_t5_city_write_execution_gate_20260527`.
- Serving overlay output: `reports\ATLAS_T5_SERVING_CITY_OVERLAY_CANDIDATE_20260527.md`; machine outputs under `tools\stage7_rewrite\reports\atlas_t5_serving_city_overlay_candidate_20260527`; candidate DB `reports\atlas_serving_city_overlay_candidate_20260527_0535\atlas_serving.sqlite`.
- LLM audit: the full source/raw serving rebuild candidate was not promoted because it regressed selected serving counts and `starts_at` coverage. The safer implementation preserves the selected serving DB and overlays only verified city fields in a report-local candidate copy.
- Counts: source/raw committed `events.city` rows `15954`; overlay mapped serving rows `50387`; candidate updates `performance_event.city=12284`, `dj_event.city=38103`, `search_document=12284`; city gaps improved `performance_event 132423->120139`, `dj_event 349045->310942`; table counts and `starts_at` gaps preserved; FTS refresh deferred `12284`; leak hits `0/0/0`.
- Self-correction: first CLI invocation exposed direct-script import path failure and was fixed. Early overlay runs timed out because search FTS/full search lookup logic was too broad; the builder now scans event search documents once and defers expensive trigram FTS refresh unless explicitly requested.
- Focused verification passed: py_compile for both scripts; overlay focused pytest `2 passed`; combined city write/preflight/time-city-overlay pytest `11 passed`; SQL readback over the candidate confirmed updated city fields; targeted URL/path/secret grep returned no hits.

2026-05-27 atlas T5 city write preflight packet addition:

- Added `tools\stage7_rewrite\scripts\build_atlas_t5_city_write_preflight_packet.py` and `tools\stage7_rewrite\tests\test_build_atlas_t5_city_write_preflight_packet.py`.
- Output packet: `reports\ATLAS_T5_CITY_WRITE_PREFLIGHT_PACKET_20260527.md`; machine outputs under `tools\stage7_rewrite\reports\atlas_t5_city_write_preflight_20260527`, including `city_write_preflight_summary.json`, `city_write_preflight_contract.json`, `city_write_preflight_ready_raw_event_rows.jsonl`, `city_write_preflight_serving_candidate_mapped_rows.jsonl`, `city_write_preflight_rollback_contracts.jsonl`, `city_write_preflight_postwrite_readback_contracts.jsonl`, `city_write_preflight_blocked_rows.jsonl`, `city_write_preflight_duplicate_selector_groups.jsonl`, and `city_write_preflight_conflict_groups.jsonl`.
- LLM audit: direct serving event IDs do not bind safely to source/raw rows. The preflight uses exact normalized event title plus conservative venue-family matching with empty raw `events.city`; OIL matching is token-bounded to avoid Boiler Room contamination.
- Counts: input serving city candidates `61266`; mapped serving candidates `50387`; blocked serving candidates `10879`; raw event city update targets `15954`; duplicate selector groups `15954`; conflict groups `0`; rollback/postwrite contracts `15954/15954`; leak hits `0/0/0`; write/public/memory rows all `0`.
- Self-correction: the first real run produced a false `sensitive_key_hits=7` because report prose mentioned `confirm token`. The leak scanner now counts only key/value-shaped sensitive fields, with a regression proving instructional text is safe while real `token:` keys still trip the guard.
- Focused verification passed: `python -m py_compile tools\stage7_rewrite\scripts\build_atlas_t5_city_write_preflight_packet.py`; focused pytest -> `4 passed`; combined city preflight + time/city/venue pytest -> `6 passed`; targeted URL/path/secret-value grep over new report/output returned no hits; summary JSON parsed successfully.

2026-05-27 atlas T5 time/city/venue gap closure packet addition:

- Added `tools\stage7_rewrite\scripts\build_atlas_t5_time_city_venue_gap_closure_packet.py` and `tools\stage7_rewrite\tests\test_build_atlas_t5_time_city_venue_gap_closure_packet.py`.
- Output packet: `reports\ATLAS_T5_TIME_CITY_VENUE_GAP_CLOSURE_PACKET_20260527.md`; machine outputs under `tools\stage7_rewrite\reports\atlas_t5_time_city_venue_gap_closure_20260527`, including `time_city_venue_gap_closure_summary.json`, `time_city_venue_gap_closure_contract.json`, `time_city_venue_gap_field_rollup.json`, `venue_city_deterministic_candidates.jsonl`, `time_title_recovery_work_orders.jsonl`, and `source_ocr_gap_recovery_work_orders.jsonl`.
- LLM audit: the avatar binary/storage lane is blocked by external root provenance, so the highest-impact safe lane is time/city/venue gap closure. Venue rollup evidence yields deterministic city repair candidates; missing `starts_at` remains a source/title/OCR lane.
- Counts: performance_event starts_at/city/venue gaps `154804/132423/66616`; dj_event starts_at/city/venue gaps `435186/349045/151231`; deterministic venue-to-city candidates `61266`; time-title recovery work orders `2000`; source/OCR gap work orders `2000`; leak hits `0/0/0`; write/public/memory rows all `0`.
- Focused verification passed: `python -m py_compile tools\stage7_rewrite\scripts\build_atlas_t5_time_city_venue_gap_closure_packet.py`; focused pytest -> `2 passed`; combined time/city/venue + completion rollup pytest -> `5 passed`; targeted URL/path/secret-value grep over new report/output returned no hits; summary JSON parsed successfully.

2026-05-27 atlas T6 avatar binary storage provenance gate addition:

- Added `tools\stage7_rewrite\scripts\build_atlas_t6_avatar_binary_storage_provenance_gate.py` and `tools\stage7_rewrite\tests\test_build_atlas_t6_avatar_binary_storage_provenance_gate.py`.
- Output packet: `reports\ATLAS_T6_AVATAR_BINARY_STORAGE_PROVENANCE_GATE_20260527.md`; machine outputs under `tools\stage7_rewrite\reports\atlas_t6_avatar_binary_storage_provenance_gate_20260527`, including `avatar_binary_storage_provenance_summary.json`, `avatar_binary_storage_provenance_contract.json`, `avatar_primary_selection_candidates.jsonl`, `avatar_binary_storage_blocked_rows.jsonl`, and `avatar_binding_repair_work_orders.jsonl`.
- LLM audit: the duplicate `DJ OXY` primary-avatar review is now deterministically resolved by largest byte size, so the remaining blocker is explicit binary source/storage target provenance plus one `DJ HEARTSTRING` binding repair.
- Counts: bound input rows `24`; primary avatar candidates/superseded/unresolved `23/1/0`; duplicate primary groups input/resolved `1/1`; binary storage ready/blocked rows `0/23`; binding repair work-order rows `1`; binary-source/storage-target provenance-ready rows `0/0`; binary files scanned/hash rows `0/0`; write/public/storage/memory rows all `0`; leak hits `0/0/0`.
- Focused verification passed: `python -m py_compile tools\stage7_rewrite\scripts\build_atlas_t6_avatar_binary_storage_provenance_gate.py`; focused pytest -> `2 passed`; combined avatar binary/entity/storage/media/validation/rollup pytest -> `16 passed`; strict raw URL/path and secret grep over new report/output returned no hits; summary JSON parsed successfully.

2026-05-27 atlas T6 avatar entity binding gate addition:

- Added `tools\stage7_rewrite\scripts\build_atlas_t6_avatar_entity_binding_gate.py` and `tools\stage7_rewrite\tests\test_build_atlas_t6_avatar_entity_binding_gate.py`.
- Output packet: `reports\ATLAS_T6_AVATAR_ENTITY_BINDING_GATE_20260527.md`; machine outputs under `tools\stage7_rewrite\reports\atlas_t6_avatar_entity_binding_gate_20260527`, including `avatar_entity_binding_summary.json`, `avatar_entity_binding_contract.json`, `avatar_entity_binding_ready_report_only.jsonl`, `avatar_entity_binding_blocked_rows.jsonl`, and `avatar_primary_selection_review_rows.jsonl`.
- LLM audit: the storage contract was necessary but insufficient for public display. The binding gate proves `24/25` DJ-first avatar rows bind to current Atlas serving DJ entities with search/graph readback, while one binding, duplicate primary-avatar selection, and storage/binary target provenance remain blocked.
- Counts: input storage-ready rows `68`; DJ-first input rows `25`; serving `dj_id` bound rows `24`; binding blocked rows `1`; unique bound serving DJ IDs `23`; search/graph readback rows `24/24`; duplicate serving-DJ avatar groups `1`; primary-review rows `2`; binary-source/storage-target provenance-ready rows `0/0`; write/public/storage/memory rows all `0`; leak hits `0/0/0`.
- Focused verification passed: `python -m py_compile tools\stage7_rewrite\scripts\build_atlas_t6_avatar_entity_binding_gate.py`; focused pytest -> `2 passed`; combined avatar entity/storage/media/validation/rollup pytest -> `14 passed`; strict raw URL/path and secret grep over new report/output returned no hits; summary JSON parsed successfully.

2026-05-27 atlas T6 avatar storage contract gate addition:

- Added `tools\stage7_rewrite\scripts\build_atlas_t6_avatar_storage_contract_gate.py` and `tools\stage7_rewrite\tests\test_build_atlas_t6_avatar_storage_contract_gate.py`.
- Output packet: `reports\ATLAS_T6_AVATAR_STORAGE_CONTRACT_GATE_20260527.md`; machine outputs under `tools\stage7_rewrite\reports\atlas_t6_avatar_storage_contract_gate_20260527`, including `avatar_storage_contract_summary.json`, `avatar_storage_contract.json`, and `avatar_storage_contract_ready_report_only.jsonl`.
- LLM audit: avatar/media discovery has advanced from stale `2` rows to v4 `68` hash-addressable artifacts, and this new gate converts those artifacts into deterministic storage/display contracts while keeping serving/public fields closed.
- Counts: input avatar rows `68`; storage-contract ready/blocked rows `68/0`; DJ-first/non-DJ ready rows `25/43`; entity-kind split `dj=25`, `venue=31`, `label=10`, `missing_rollup=2`; platform split `youtube=47`, `instagram=19`, `soundcloud=2`; write/public/storage/memory rows all `0`; leak hits `0/0/0`.
- Focused verification passed: `python -m py_compile tools\stage7_rewrite\scripts\build_atlas_t6_avatar_storage_contract_gate.py`; focused pytest -> `2 passed`; combined avatar storage/media/validation/rollup pytest -> `12 passed`; strict raw URL/path and secret grep over new report/output returned no hits; summary JSON parsed successfully.

2026-05-27 atlas T6 avatar/media recovery packet addition:

- Added `tools\stage7_rewrite\scripts\build_atlas_t6_avatar_media_recovery_packet.py` and `tools\stage7_rewrite\tests\test_build_atlas_t6_avatar_media_recovery_packet.py`.
- Output packet: `reports\ATLAS_T6_AVATAR_MEDIA_RECOVERY_PACKET_20260527.md`; machine outputs under `tools\stage7_rewrite\reports\atlas_t6_avatar_media_recovery_packet_20260527`, including `avatar_media_recovery_summary.json`, `avatar_media_recovery_contract.json`, and `avatar_media_recovery_work_orders.jsonl`.
- LLM audit: the old validation gate's `2` avatar rows were stale because the newer v4 redacted sidecar manifest had `68` avatar artifacts. The new packet consumes v4 hash/redacted evidence, keeps raw URL/path fields out of outputs, and separates storage contract, DJ binding review, non-DJ scope review, missing-rollup review, and public-serving-field gate work.
- Counts: avatar artifacts input/hash-addressable/DJ-first/non-DJ/missing-rollup `68/68/25/41/2`; media signal rollups total/DJ-first `74/25`; old validation avatar actual/hash-ready/blocked `2/0/2`; completion rollup DJ avatar/media missing `53,555/53,555`; leak hits `0/0/0`.
- Focused verification passed: `python -m py_compile tools\stage7_rewrite\scripts\build_atlas_t6_avatar_media_recovery_packet.py`; focused pytest -> `3 passed`; combined avatar/media + sidecar validation + completion rollup pytest -> `10 passed`; strict raw URL/key/path grep over new report/output returned no hits; summary JSON parsed successfully.

2026-05-27 atlas T5/T6 sidecar social read-model rendered UI smoke addition and UI workbench fix:

- Added `tools\stage7_rewrite\scripts\build_atlas_t6_sidecar_social_read_model_rendered_ui_smoke.py` and `tools\stage7_rewrite\tests\test_build_atlas_t6_sidecar_social_read_model_rendered_ui_smoke.py`.
- Updated `tools\stage7_rewrite\scripts\build_atlas_t6_sidecar_social_read_model_ui_integration_review.py` and `tools\stage7_rewrite\tests\test_build_atlas_t6_sidecar_social_read_model_ui_integration_review.py`.
- Output packet: `reports\ATLAS_T5_T6_SIDECAR_SOCIAL_READ_MODEL_RENDERED_UI_SMOKE_20260527.md`; machine outputs under `tools\stage7_rewrite\reports\atlas_t6_sidecar_social_read_model_rendered_ui_smoke_t5_t6_20260527`, including `social_read_model_rendered_ui_contract.json` and `social_read_model_rendered_ui_fixture.html`.
- LLM audit: the 02:08 workbench had a real sample-shape bug. `platform_filter` consumer samples were compacted as DJ social cards, producing 12 blank cards. The fixed integration builder separates `dj_social_card` and `platform_filter`; regenerated 02:08 output has `sample_cards=12`, `platform_filter_samples=12`, and `blank_sample_cards=0`.
- Rendered smoke proves route-panel/sample-card/graph-preview readiness with `rendered_route_panels=5`, `rendered_sample_cards=12`, preview graph `75/38/37`, and leak hits `0/0/0`. It remains report-local static UI evidence only.
- Focused verification passed: `python -m py_compile` for both builders; focused pytest -> `9 passed`; combined social-read-model pytest -> `25 passed`; strict raw URL/key/path grep over regenerated 02:08 and new 02:17 outputs returned no hits; summary/contract JSON parsed successfully.

2026-05-27 atlas T5/T6 sidecar social read-model consumer smoke addition:

- Added `tools\stage7_rewrite\scripts\build_atlas_t6_sidecar_social_read_model_consumer_smoke.py` and `tools\stage7_rewrite\tests\test_build_atlas_t6_sidecar_social_read_model_consumer_smoke.py`.
- Output packet: `reports\ATLAS_T5_T6_SIDECAR_SOCIAL_READ_MODEL_CONSUMER_SMOKE_20260527.md`; machine outputs under `tools\stage7_rewrite\reports\atlas_t6_sidecar_social_read_model_consumer_smoke_t5_t6_20260527`, including `social_read_model_consumer_contract.json`.
- The script remains report-only. It consumes the 2026-05-27 social read-model candidate manifest, validates local UI/API route contracts, detail/search/graph subject alignment, platform facets, samples, filter state, write guards, and leak guards, and keeps persistence/public/memory guards closed.
- LLM audit: the 01:30 candidate was valid but not yet consumer-shaped. This smoke proves local consumer readiness while keeping source/raw DB, selected serving, graph/vector, public pointer, upload, and memory write guards closed.
- LLM self-correction: focused tests caught temp-path false positives outside the repo, and real data exposed safe human platform labels such as `githubgist[github]` and `flickr groups`; path rendering and platform-label validation were tightened without allowing URL/path/credential-shaped content.
- Focused verification passed: `python -m py_compile tools\stage7_rewrite\scripts\build_atlas_t6_sidecar_social_read_model_consumer_smoke.py`; focused pytest -> `8 passed`; combined social-read-model consumer/candidate/persistence/attach/overlay/rollup pytest -> `32 passed`; strict raw URL/key/path grep returned no hits; summary JSON parsed successfully.

2026-05-27 atlas T5/T6 sidecar social read-model candidate update:

- Updated `tools\stage7_rewrite\scripts\build_atlas_t6_sidecar_social_read_model_candidate.py` and `tools\stage7_rewrite\tests\test_build_atlas_t6_sidecar_social_read_model_candidate.py`.
- Output packet: `reports\ATLAS_T5_T6_SIDECAR_SOCIAL_READ_MODEL_CANDIDATE_20260527.md`; machine outputs under `tools\stage7_rewrite\reports\atlas_t6_sidecar_social_read_model_candidate_t5_t6_20260527`, including `social_read_model_candidate_manifest.json`.
- The script remains report-only. It now consumes the 2026-05-27 persistence contract as a hard gate, validates count alignment with the prior attach API contract, emits local social overview/detail/search/graph/platform fixtures, and records prewrite, rollback, and postwrite requirements for any later derived serving candidate.
- LLM audit: the earlier default path was stale on the 2026-05-26 attach-smoke-only contract. The corrected path proves current social/profile/outlink fixture readiness while keeping source/raw DB, selected serving, graph/vector, public pointer, upload, and memory write guards closed.
- LLM self-correction: focused tests and the real run exposed a false-positive leak scan on the safe zero-valued metric label `local_secret_path`; the scanner now allows safe metric keys only as metric labels while still blocking credential-shaped content.
- Focused verification passed: `python -m py_compile tools\stage7_rewrite\scripts\build_atlas_t6_sidecar_social_read_model_candidate.py`; focused pytest -> `5 passed`; combined social-read-model/persistence/attach/overlay/rollup pytest -> `19 passed`; strict raw URL/key/path grep returned no hits; summary JSON parsed successfully.

2026-05-27 atlas T7 HUAIDJ root graph home / Turnstile SSOT sync:

- Added report-only SSOT evidence `reports\ATLAS_T7_HUAIDJ_ROOT_GRAPH_HOME_SSOT_SYNC_20260527.md` and structured summary `tools\stage7_rewrite\reports\atlas_t7_huaidj_root_graph_home_ssot_sync_20260527\root_graph_home_ssot_sync_summary.json`.
- LLM audit: `docs\current-runtime.md` had advanced to the 00:48 Atlas Turnstile failure-handling fix and the 00:39 HUAIDJ root graph home boundary while router/status/code-map surfaces still treated the 00:27 rollup as active. The stale state could cause repeated SSOT work or mistaken public upload retry.
- Boundary: docs/status sync only; no code path, source/raw DB, serving SQLite, Neo4j, Qdrant, production SQLite, CloudRun, mini-program, memory, secret, 9router, destructive Git, or D: root mutation.
- Verification target: JSON summary parse, heartbeat JSON parse, and docs build after SSOT edits.

2026-05-27 atlas T5/T6 DJ completion overlay rollup addition:

- Added `tools\stage7_rewrite\scripts\build_atlas_dj_completion_overlay_rollup.py` and `tools\stage7_rewrite\tests\test_build_atlas_dj_completion_overlay_rollup.py`.
- Output packet: `reports\ATLAS_T5_T6_DJ_COMPLETION_OVERLAY_ROLLUP_20260527.md`; machine outputs under `tools\stage7_rewrite\reports\atlas_dj_completion_overlay_rollup_t5_t6_20260527`.
- The script is report-only. It consumes only existing redacted/report-local artifacts, rolls up DJ completion counts, sidecar overlay readiness, quality gaps, SSOT drift, and next work orders, and keeps all DB/public/memory write guards false.
- LLM audit: Atlas is now DJ-first and large-scale (`53,555` DJs, `508,049` performance events, `1,285,827` DJ-event edges, `701,396` directed relations), but full production still has explicit gaps: avatar/media all empty, starts_at/city/venue gaps remain material, and sidecar overlay persistence needs a later schema/merge decision. The script also surfaced one SSOT drift row after the 00:10 protected graph UI upload boundary.
- Focused verification passed before SSOT closeout: script `py_compile`; focused pytest `3 passed`; combined completion/overlay/UI/attach pytest `19 passed`; strict raw URL/local-path/credential grep returned no hits; summary JSON parsed successfully.

2026-05-26 atlas T5/T6 sidecar overlay UI integration smoke addition:

- Added `tools\stage7_rewrite\scripts\build_atlas_t6_sidecar_overlay_ui_integration_smoke.py` and `tools\stage7_rewrite\tests\test_build_atlas_t6_sidecar_overlay_ui_integration_smoke.py`.
- Output packet: `reports\ATLAS_T5_T6_SIDECAR_OVERLAY_UI_INTEGRATION_SMOKE_20260526.md`; machine outputs under `tools\stage7_rewrite\reports\atlas_t6_sidecar_overlay_ui_integration_smoke_t5_t6_20260526`, including `overlay_social_ui_integration_contract.json`.
- The script is report-only. It consumes the 23:24 overlay UI contract, validates view model/Cytoscape/filter/sample coverage, subset integrity, and leak guards, and keeps all write/public/memory guards false.
- LLM audit: the overlay sidecar is now represented as local UI integration evidence with attach-ready/blocked rows `1,975/0`, Cytoscape elements/nodes/edges `136/34/102`, DJ/platform/city nodes `8/20/6`, platform/city edges `94/8`, detail/graph/integration samples `8/8/8`, overlay link/profile/outlink rows `18,710/15,715/2,995`, and leak hits `0/0/0`.
- LLM self-correction: the first real run over-blocked detail-only platforms missing from the top platform facets. The builder now emits `sample_only_platforms` and only blocks unsafe URL-like platform labels.
- Focused verification passed: `python -m py_compile tools\stage7_rewrite\scripts\build_atlas_t6_sidecar_overlay_ui_integration_smoke.py`; focused pytest -> `8 passed`; combined UI-integration/consumer/candidate/attach/overlay/validation/redacted-manifest/completion pytest -> `41 passed`; strict raw URL/local-path/credential grep returned no hits; summary JSON parsed successfully.

2026-05-26 atlas T5/T6 sidecar overlay local API consumer smoke addition:

- Added `tools\stage7_rewrite\scripts\build_atlas_t6_sidecar_overlay_local_api_consumer_smoke.py` and `tools\stage7_rewrite\tests\test_build_atlas_t6_sidecar_overlay_local_api_consumer_smoke.py`.
- Output packet: `reports\ATLAS_T5_T6_SIDECAR_OVERLAY_LOCAL_API_CONSUMER_SMOKE_20260526.md`; machine outputs under `tools\stage7_rewrite\reports\atlas_t6_sidecar_overlay_local_api_consumer_smoke_t5_t6_20260526`, including `overlay_social_ui_contract.json`.
- The script is report-only. It consumes the overlay local API candidate manifest and fixtures, validates UI/API consumer route contracts, detail/search/platform/graph consistency, subset coverage, and leak guards, and keeps all write/public/memory guards false.
- LLM audit: the overlay sidecar is now represented as local UI/API consumer contract evidence with route contracts `5`, overview/detail/search/platform/graph rows `1/24/1/12/8`, search item rows `12`, graph sample DJ rows `8`, attach-ready/blocked rows `1,975/0`, platform-host rows `2,024`, overlay link/profile/outlink rows `18,710/15,715/2,995`, and leak hits `0/0/0`.
- LLM self-correction: focused tests exposed a zero-value parser bug where valid `0` outlink totals were treated as missing, and real data exposed safe colon host labels such as `facebook:http:`. The builder now parses zeros explicitly and allows safe colon labels without allowing raw URL/path/credential shapes.
- Focused verification passed: `python -m py_compile tools\stage7_rewrite\scripts\build_atlas_t6_sidecar_overlay_local_api_consumer_smoke.py`; focused pytest -> `8 passed`; combined consumer/candidate/attach/overlay/validation/redacted-manifest/completion pytest -> `33 passed`; strict raw URL/local-path/credential grep returned no hits; summary JSON parsed successfully.

2026-05-26 atlas T5/T6 sidecar overlay local API candidate addition:

- Added `tools\stage7_rewrite\scripts\build_atlas_t6_sidecar_overlay_local_api_candidate.py` and `tools\stage7_rewrite\tests\test_build_atlas_t6_sidecar_overlay_local_api_candidate.py`.
- Output packet: `reports\ATLAS_T5_T6_SIDECAR_OVERLAY_LOCAL_API_CANDIDATE_20260526.md`; machine outputs under `tools\stage7_rewrite\reports\atlas_t6_sidecar_overlay_local_api_candidate_t5_t6_20260526`, including `overlay_social_local_api_candidate_manifest.json`.
- The script is report-only. It consumes the redacted overlay API contract, ready rows, blocked rows, platform rollup, and detail samples from the 22:37 attach smoke; emits overview/detail/search/platform/graph fixtures; and keeps all write/public/memory guards false.
- LLM audit: the overlay sidecar is now represented as local consumer API fixtures with route contracts `5`, overview/detail/search/platform/graph responses `1/24/1/12/8`, attach-ready/blocked rows `1,975/0`, platform-host rows `2,024`, overlay link/profile/outlink rows `18,710/15,715/2,995`, and leak hits `0/0/0`.
- LLM self-correction: the first real run over-blocked detail rows because real samples store `write_status` inside `body`; the builder now accepts top-level or body-level `report_only`, and regression coverage locks the body-only case.
- Focused verification passed: `python -m py_compile tools\stage7_rewrite\scripts\build_atlas_t6_sidecar_overlay_local_api_candidate.py`; focused pytest -> `7 passed`; combined local-API/attach/overlay/validation/redacted-manifest/completion pytest -> `25 passed`; strict raw URL/local-path/credential grep returned no hits; summary JSON parsed successfully.

2026-05-26 atlas T5/T6 sidecar overlay serving attach smoke addition:

- Added `tools\stage7_rewrite\scripts\build_atlas_t6_sidecar_overlay_serving_attach_smoke.py` and `tools\stage7_rewrite\tests\test_build_atlas_t6_sidecar_overlay_serving_attach_smoke.py`.
- Output packet: `reports\ATLAS_T5_T6_SIDECAR_OVERLAY_SERVING_ATTACH_SMOKE_20260526.md`; machine outputs under `tools\stage7_rewrite\reports\atlas_t6_sidecar_overlay_serving_attach_smoke_t5_t6_20260526`, including `overlay_social_api_contract.json`.
- The script is report-only. It opens the selected serving SQLite read-only, attaches the report-local sidecar overlay SQLite read-only, validates DJ entity joins to profile/search/graph-window surfaces, emits API contract/detail/platform outputs, and keeps all write/public/memory guards false.
- LLM audit: the overlay is now locally consumable by serving/search/graph/API surfaces: `1,975` overlay DJ entities join `dj_profile/search_document/graph_window`, serving event/relation edges are `436,835/364,868`, attach-ready/blocked rows are `1,975/0`, duplicate selector groups are `0`, and leak hits are `0/0/0`.
- LLM self-correction: first real attach attempts were too slow because of per-entity correlated/full-table SQLite reads over the multi-GB serving DB. The builder now avoids full serving `quick_check` and uses batched Python `IN` reads, bringing the real attach smoke down to about one second.
- Focused verification passed: `python -m py_compile tools\stage7_rewrite\scripts\build_atlas_t6_sidecar_overlay_serving_attach_smoke.py`; focused pytest -> `5 passed`; combined overlay attach/overlay DB/validation/redacted-manifest/completion pytest -> `18 passed`; strict raw URL/local-path/credential grep returned no hits.

2026-05-26 atlas T5/T6 sidecar new DB overlay addition:

- Added `tools\stage7_rewrite\scripts\build_atlas_t6_sidecar_new_db_overlay.py` and `tools\stage7_rewrite\tests\test_build_atlas_t6_sidecar_new_db_overlay.py`.
- Output packet: `reports\ATLAS_T5_T6_SIDECAR_NEW_DB_OVERLAY_20260526.md`; machine outputs under `tools\stage7_rewrite\reports\atlas_t6_sidecar_new_db_overlay_t5_t6_20260526`, including `atlas_t6_sidecar_social_overlay.sqlite`.
- The script writes a report-local SQLite overlay only. It opens the explicit source/raw target DB read-only, records a sanitized schema snapshot, verifies that native social/outlink tables are absent, writes validated profile/outlink rows into the overlay, and emits postwrite readback plus rollback contract.
- LLM audit: in-place source/raw social merge is not safe against the current 4GB Atlas SQLite because it has no native social link tables. The overlay advances the full-production path without modifying the source/raw DB: `18,710` social rows, `1,975` DJ entities, duplicate selector rows `0`, write-guard-open rows `0`, leak hits `0/0/0`.
- LLM self-correction: focused tests and real data exposed two scanner issues. Schema identifiers such as `source_token_hash` are now hash-redacted in outputs, while legitimate artist/domain values containing `Secret` are no longer treated as credential leaks unless they match credential-shaped value patterns.
- Focused verification passed: `python -m py_compile tools\stage7_rewrite\scripts\build_atlas_t6_sidecar_new_db_overlay.py`; focused pytest -> `3 passed`; combined sidecar overlay/validation/redacted-manifest/completion pytest -> `13 passed`; strict raw URL/local-path/credential grep returned no hits.

2026-05-26 atlas T5/T6 sidecar manifest validation gate addition:

- Added `tools\stage7_rewrite\scripts\build_atlas_t6_sidecar_manifest_validation_gate.py` and `tools\stage7_rewrite\tests\test_build_atlas_t6_sidecar_manifest_validation_gate.py`.
- Output packet: `reports\ATLAS_T5_T6_SIDECAR_MANIFEST_VALIDATION_GATE_20260526.md`; machine outputs under `tools\stage7_rewrite\reports\atlas_t6_sidecar_manifest_validation_gate_t5_t6_20260526`.
- The script is report-only. It consumes the T6 hash/redacted manifest artifacts, opens the selected serving SQLite read-only, validates manifest counts, write guards, redaction, duplicate candidate/canonical URL-key drift, serving DJ entity coverage, entity rollup consistency, identity review blockers, avatar blockers, and upstream blocker reasons.
- LLM audit: profile/outlink sidecar rows now have a T5-consumable merge-precheck scope (`18,710` rows) while `31` identity candidates and `2` avatar rows remain blocked/review-only. No source/raw DB write, serving rebuild/write, graph/vector/public mutation, huaidj.club upload, mini-program upload/review, or memory write occurred.
- LLM self-correction: focused tests exposed that input payload leaks must be included in the validation leak scan, not only sanitized validation output rows; the script now scans manifest input rows before emitting report-only summaries.
- Focused verification passed: `python -m py_compile tools\stage7_rewrite\scripts\build_atlas_t6_sidecar_manifest_validation_gate.py`; focused pytest -> `4 passed`; combined sidecar validation/redacted-manifest/completion pytest -> `10 passed`; strict raw URL/local-path/WSL-path grep returned no hits.

2026-05-26 atlas T6 sidecar hash/redacted manifest addition:

- Added `tools\stage7_rewrite\scripts\build_atlas_t6_sidecar_redacted_manifest.py` and `tools\stage7_rewrite\tests\test_build_atlas_t6_sidecar_redacted_manifest.py`.
- Output packet: `reports\ATLAS_T6_SIDECAR_REDACTED_MANIFEST_20260526.md`; machine outputs under `tools\stage7_rewrite\reports\atlas_t6_sidecar_redacted_manifest_20260526`.
- The script is report-only. It copies the bounded WSL scratch SQLite to a temporary local snapshot for read-only access, joins sidecar candidates to selected serving DJ profiles by normalized names, emits only hashed/redacted URL/path evidence, and keeps all write/public/memory guards false.
- LLM audit: the WSL sidecar is now in a T5-consumable redacted shape with `18,741` joined candidates, `1,986` entity rollups, `2` avatar artifact rows, `12,260` blockers, and leak hits `0/0/0`. Remaining adoption risk is T5 validation and a separate new-Atlas-DB merge gate, not raw URL/path leakage.
- LLM self-correction: real scratch rows exposed non-numeric confidence labels and malformed pseudo-URLs; the builder now maps non-numeric confidence to `0.0` and blocks invalid URLs instead of crashing or emitting raw values.
- Focused verification passed: `python -m py_compile tools\stage7_rewrite\scripts\build_atlas_t6_sidecar_redacted_manifest.py`; focused pytest -> `3 passed`; combined sidecar/completion pytest -> `6 passed`; strict URL/key/path grep returned no hits.

2026-05-26 atlas T6/T5 manual participant remaining-identity readback gate addition:

- Reused and hardened `tools\stage7_rewrite\scripts\build_atlas_social_manual_participant_event_identity_readback_gate.py` and `tools\stage7_rewrite\tests\test_build_atlas_social_manual_participant_event_identity_readback_gate.py`.
- Output packet: `reports\ATLAS_T6_MANUAL_PARTICIPANT_REMAINING_IDENTITY_READBACK_GATE_20260526.md`; machine outputs under `tools\stage7_rewrite\reports\atlas_social_manual_participant_remaining_identity_readback_gate_q6_20260526`.
- The script is report-only. It consumes the remaining-identity recovery readback candidates, opens selected serving SQLite read-only, validates selected event ids, source refs, source hashes, venue/date consistency, and participant evidence, then emits ready/blocked rows, date/venue split rows, schema snapshot, and summary outputs.
- LLM audit: the remaining manual identity lane now has `4` selected-serving readback-ready rows and `0` readback blockers, covering `11` selected event ids with leak hits `0/0/0`. All write/promotion fields remain `0`.
- LLM self-correction: readback venue normalization now covers additional `OIL`, `ClubMe`, and `Coolwave` variants; sensitive-looking source-kind wording is scrubbed before report output and strict leak/key scans.
- Focused verification passed: `python -m py_compile tools\stage7_rewrite\scripts\build_atlas_social_manual_participant_event_identity_readback_gate.py`; focused remaining-identity/readback pytest -> `12 passed`; combined remaining-identity/readback/midnight/blocked-identity pytest -> `29 passed`; strict URL/key/path grep returned no hits.

2026-05-26 atlas T6/T5 manual participant remaining-identity recovery gate addition:

- Added `tools\stage7_rewrite\scripts\build_atlas_social_manual_participant_remaining_identity_recovery_gate.py` and `tools\stage7_rewrite\tests\test_build_atlas_social_manual_participant_remaining_identity_recovery_gate.py`.
- Output packet: `reports\ATLAS_T6_MANUAL_PARTICIPANT_REMAINING_IDENTITY_RECOVERY_GATE_20260526.md`; machine outputs under `tools\stage7_rewrite\reports\atlas_social_manual_participant_remaining_identity_recovery_q6_20260526`.
- The script is report-only. It consumes five remaining blocked-identity work-order queues, groups by recovery lane, emits deterministic readback candidates versus explicit blocker rows, validates redaction/leak checks, and keeps all acceptance/write/public gates closed.
- LLM audit: the run converted `9` remaining work orders into `4` readback candidates and `5` precise blockers. Candidate split was same-date tiebreak `2` and venue-alias `2`; blockers were event-date/source-year `1`, venue-alias date mismatch `2`, multi-venue `1`, and low-title `1`; leak hits were `0/0/0`.
- Focused verification passed through the combined test matrix above.

2026-05-26 atlas T6/T5 manual participant overnight-midnight acceptance write-gate addition:

- Added `tools\stage7_rewrite\scripts\build_atlas_social_manual_participant_overnight_midnight_acceptance_write_gate.py` and `tools\stage7_rewrite\tests\test_build_atlas_social_manual_participant_overnight_midnight_acceptance_write_gate.py`.
- Output packet: `reports\ATLAS_T6_MANUAL_PARTICIPANT_OVERNIGHT_MIDNIGHT_ACCEPTANCE_WRITE_GATE_20260526.md`; machine outputs under `tools\stage7_rewrite\reports\atlas_social_manual_participant_overnight_midnight_acceptance_write_gate_q6_20260526`.
- The script is report-only. It consumes the 15:10 overnight-midnight readback-ready row, validates manual acceptance contract requirements, and blocks mutation because source/raw target DB provenance is missing.
- LLM audit: the row is manual-ready at contract level (`1/1/1`), but source/raw target DB ready/blocked is `0/1`, write execution allowed is `0`, leak hits are `0/0/0`, and all write/promotion rows remain `0`.
- Focused verification passed: `python -m py_compile tools\stage7_rewrite\scripts\build_atlas_social_manual_participant_overnight_midnight_acceptance_write_gate.py`; focused pytest -> `6 passed`.

2026-05-26 atlas T6/T5 manual participant overnight-midnight readback gate addition:

- Added `tools\stage7_rewrite\scripts\build_atlas_social_manual_participant_overnight_midnight_readback_gate.py` and `tools\stage7_rewrite\tests\test_build_atlas_social_manual_participant_overnight_midnight_readback_gate.py`.
- Output packet: `reports\ATLAS_T6_MANUAL_PARTICIPANT_OVERNIGHT_MIDNIGHT_READBACK_GATE_20260526.md`; machine outputs under `tools\stage7_rewrite\reports\atlas_social_manual_participant_overnight_midnight_readback_gate_q6_20260526`.
- The script is report-only. It consumes the 14:42 midnight-boundary correction candidate, opens selected serving SQLite read-only, validates selected event ids, source refs, source hashes, boundary dates, and participant evidence, then emits ready/blocked rows, boundary segment readback rows, schema snapshot, and summary outputs.
- LLM audit: the row now read backs as one midnight-boundary candidate with input/readback/ready/blocked rows `1/1/1/0`, boundary segment readback rows `2`, boundary-start/midnight-date event rows `2/3`, selected event ids `5`, min participant evidence `1`, and leak hits `0/0/0`. Non-identical equivalent source hashes are warning-only because the expected hash is present.
- LLM self-correction: the first real summary counted distinct boundary date values instead of event rows. The builder now records `date_counts` and regressions cover the `2/3` boundary-start/midnight event-row split.
- Focused verification passed: `python -m py_compile tools\stage7_rewrite\scripts\build_atlas_social_manual_participant_overnight_midnight_readback_gate.py`; `python -m pytest tools\stage7_rewrite\tests\test_build_atlas_social_manual_participant_overnight_midnight_readback_gate.py -q` -> `7 passed`; combined midnight-readback/correction/span/source-date-readback pytest -> `22 passed`; strict URL/key/path grep returned no hits.

2026-05-26 atlas T6/T5 manual participant overnight-midnight correction addition:

- Added `tools\stage7_rewrite\scripts\build_atlas_social_manual_participant_overnight_midnight_correction.py` and `tools\stage7_rewrite\tests\test_build_atlas_social_manual_participant_overnight_midnight_correction.py`.
- Output packet: `reports\ATLAS_T6_MANUAL_PARTICIPANT_OVERNIGHT_MIDNIGHT_CORRECTION_20260526.md`; machine outputs under `tools\stage7_rewrite\reports\atlas_social_manual_participant_overnight_midnight_correction_q6_20260526`.
- The script is report-only. It consumes the 14:38 overnight/span readback candidate and user correction `实际上应该是今天半夜`, supersedes the two-date split interpretation, and normalizes the row to `2019-12-31` crossing to `2020-01-01 00:00` Asia/Shanghai.
- LLM audit: the prior split packet remains segment/source-ref evidence but is no longer the active interpretation for this row. The real packet verifies one midnight-boundary candidate, zero blocked rows, five selected event ids, and leak hits `0/0/0`.
- Focused verification passed: `python -m py_compile tools\stage7_rewrite\scripts\build_atlas_social_manual_participant_overnight_midnight_correction.py`; `python -m pytest tools\stage7_rewrite\tests\test_build_atlas_social_manual_participant_overnight_midnight_correction.py -q` -> `4 passed`; combined midnight/span/source-date-context/source-date-readback pytest -> `21 passed`; strict URL/key/path grep returned no hits.
2026-05-26 atlas T6/T5 manual participant source-date acceptance write-gate addition:

- Added `tools\stage7_rewrite\scripts\build_atlas_social_manual_participant_source_date_acceptance_write_gate.py` and `tools\stage7_rewrite\tests\test_build_atlas_social_manual_participant_source_date_acceptance_write_gate.py`.
- Output packet: `reports\ATLAS_T6_MANUAL_PARTICIPANT_SOURCE_DATE_ACCEPTANCE_WRITE_GATE_20260526.md`; machine outputs under `tools\stage7_rewrite\reports\atlas_social_manual_participant_source_date_acceptance_write_gate_q6_20260526`.
- The script is report-only. It consumes the 13:10 source-date readback-ready rows, validates source/event/participant evidence and target-DB provenance blocker state, emits deterministic selectors, dry-run work orders, rollback contracts, postwrite readback contracts, and keeps all acceptance/write/public gates closed.
- LLM audit: the `3` source-date rows are manual acceptance-precheck ready at report-only contract level, but source/raw target DB provenance is still missing (`0` direct explicit target DB paths, ready/blocked `0/46` upstream). The real packet verifies source/raw target DB blocked rows `3`, write execution allowed rows `0`, and leak hits `0/0/0`.
- LLM self-correction: the first real run misread legacy target-DB provenance count names and displayed blocked provenance rows as `0`. The builder now supports both legacy (`target_db_provenance_blocked_rows`) and current count names; regression coverage locks this.
- Focused verification passed: `python -m py_compile tools\stage7_rewrite\scripts\build_atlas_social_manual_participant_source_date_acceptance_write_gate.py`; `python -m pytest tools\stage7_rewrite\tests\test_build_atlas_social_manual_participant_source_date_acceptance_write_gate.py -q` -> `6 passed`; combined source-date acceptance/source-date readback/target-DB provenance pytest -> `17 passed`; strict URL/key/path grep returned no hits.

2026-05-26 atlas T6/T5 manual participant source-date readback gate addition:

- Added `tools\stage7_rewrite\scripts\build_atlas_social_manual_participant_source_date_readback_gate.py` and `tools\stage7_rewrite\tests\test_build_atlas_social_manual_participant_source_date_readback_gate.py`.
- Output packet: `reports\ATLAS_T6_MANUAL_PARTICIPANT_SOURCE_DATE_READBACK_GATE_20260526.md`; machine outputs under `tools\stage7_rewrite\reports\atlas_social_manual_participant_source_date_readback_gate_q6_20260526`.
- The script is report-only. It consumes the 12:21 source-date-context candidate-ready rows, opens selected serving SQLite read-only, validates source/event/participant evidence and selected dates, emits readback/ready/blocked/schema outputs, and keeps all acceptance/write/public gates closed.
- LLM audit: the 08:05 source/raw target DB provenance blocker still has no new explicit target DB, so the useful safe advance was selected-serving readback for the `3` source-date candidates rather than mutation. The real packet verifies ready rows `3`, blocked rows `0`, unique selected event ids/dates `6/3`, and leak hits `0/0/0`.
- LLM self-correction: strict leak grep caught sensitive-key wording in an upstream source-kind label (`queue_token_account_title_exact`), so report outputs now scrub that label class and regression covers it.
- Focused verification passed: `python -m py_compile tools\stage7_rewrite\scripts\build_atlas_social_manual_participant_source_date_readback_gate.py`; `python -m pytest tools\stage7_rewrite\tests\test_build_atlas_social_manual_participant_source_date_readback_gate.py -q` -> `7 passed`; combined source-date-readback/source-date-context/event-identity pytest -> `20 passed`; row-count check `3/3/3/0/6/3`; strict URL/key/path grep returned no hits.

2026-05-26 atlas T6/T5 manual participant source-date-context recovery addition:

- Added `tools\stage7_rewrite\scripts\build_atlas_social_manual_participant_source_date_context_recovery.py` and `tools\stage7_rewrite\tests\test_build_atlas_social_manual_participant_source_date_context_recovery.py`.
- Output packet: `reports\ATLAS_T6_MANUAL_PARTICIPANT_SOURCE_DATE_CONTEXT_RECOVERY_20260526.md`; machine outputs under `tools\stage7_rewrite\reports\atlas_social_manual_participant_source_date_context_recovery_q6_20260526`.
- The script is report-only. It consumes the 11:18 source-date-context work orders, derives deterministic source-ref lineage and title-weekday signals, keeps cross-year countdown evidence in span/split review, validates redaction/leak checks, and keeps all acceptance/write/public gates closed.
- LLM audit: the 08:05 source/raw target DB provenance blocker still has no new target DB, so the useful safe advance was source-date-context recovery over the 4 work orders. The real packet verifies candidate-ready rows `3`, overnight/span review rows `1`, and leak hits `0/0/0`.
- Focused verification passed: `python -m py_compile tools\stage7_rewrite\scripts\build_atlas_social_manual_participant_source_date_context_recovery.py`; `python -m pytest tools\stage7_rewrite\tests\test_build_atlas_social_manual_participant_source_date_context_recovery.py -q` -> `6 passed`; combined source-date-context/blocked-identity/event-identity pytest -> `15 passed`; strict URL/key/path grep returned no hits.

2026-05-26 atlas T6/T5 manual participant blocked identity review addition:

- Added `tools\stage7_rewrite\scripts\build_atlas_social_manual_participant_blocked_identity_review.py` and `tools\stage7_rewrite\tests\test_build_atlas_social_manual_participant_blocked_identity_review.py`.
- Output packet: `reports\ATLAS_T6_MANUAL_PARTICIPANT_BLOCKED_IDENTITY_REVIEW_20260526.md`; machine outputs under `tools\stage7_rewrite\reports\atlas_social_manual_participant_blocked_identity_review_q6_20260526`.
- The script is report-only. It consumes the 08:43 still-blocked manual event-identity rows, emits source-date-context, event-date/source-year, same-date tiebreak, venue-alias lineage, multi-venue, and low-title review work orders, validates redaction/leak checks, and keeps all acceptance/write/public gates closed.
- LLM audit: the 10:55 visual response smoke was already verified, and source/raw target DB provenance remained blocked. The high-value safe advance was to split the `13` still-blocked identity rows into precise recovery queues instead of rerunning visual/API smoke or blocked provenance. The real packet verifies work-order rows `13`, source-account batches `4`, lane split `4/1/2/4/1/1`, and leak hits `0/0/0`.
- Focused verification passed: `python -m py_compile tools\stage7_rewrite\scripts\build_atlas_social_manual_participant_blocked_identity_review.py`; `python -m pytest tools\stage7_rewrite\tests\test_build_atlas_social_manual_participant_blocked_identity_review.py -q` -> `4 passed`; combined blocked-identity/event-identity/blocker-recovery pytest -> `13 passed`; strict URL/key/path grep returned no hits.

2026-05-26 atlas T6/T5 manual participant visual API response smoke addition:

- Added `tools\stage7_rewrite\scripts\build_atlas_social_manual_participant_visual_api_response_smoke.py` and `tools\stage7_rewrite\tests\test_build_atlas_social_manual_participant_visual_api_response_smoke.py`.
- Output packet: `reports\ATLAS_T6_MANUAL_PARTICIPANT_VISUAL_API_RESPONSE_SMOKE_20260526.md`; machine outputs under `tools\stage7_rewrite\reports\atlas_social_manual_participant_visual_api_response_smoke_q6_20260526`.
- The script is report-only. It consumes the 10:40 visual API drilldown contract and samples, emits overview/detail/neighbor/query/cluster response fixtures, validates route contracts, response counts, detail-neighbor degree consistency, query facet counts, redaction/leak checks, and keeps all acceptance/write/public gates closed.
- LLM audit: source/raw target DB provenance remained blocked, so the safe high-value advance was proving local API response fixture readiness from existing drilldown evidence instead of mutation. The real packet verifies route contracts `5`, response fixtures `1/12/12/8/8`, detail-neighbor mismatch rows `0`, query-facet mismatch rows `0`, and leak hits `0/0/0`.
- Focused verification passed: `python -m py_compile tools\stage7_rewrite\scripts\build_atlas_social_manual_participant_visual_api_response_smoke.py`; `python -m pytest tools\stage7_rewrite\tests\test_build_atlas_social_manual_participant_visual_api_response_smoke.py -q` -> `6 passed`; combined visual-response/API-drilldown/smoke/export/graph-search pytest -> `27 passed`; strict URL/key/path grep returned no hits.

2026-05-26 atlas T6/T5 manual participant visual API drilldown addition:

- Added `tools\stage7_rewrite\scripts\build_atlas_social_manual_participant_visual_api_drilldown.py` and `tools\stage7_rewrite\tests\test_build_atlas_social_manual_participant_visual_api_drilldown.py`.
- Output packet: `reports\ATLAS_T6_MANUAL_PARTICIPANT_VISUAL_API_DRILLDOWN_20260526.md`; machine outputs under `tools\stage7_rewrite\reports\atlas_social_manual_participant_visual_api_drilldown_q6_20260526`.
- The script is report-only. It consumes the 10:11 visual UI contract, emits API route/detail/search/neighbor/cluster drilldown samples, validates route contracts, duplicate/dangling/search/window coverage, and keeps all acceptance/write/public gates closed.
- LLM audit: source/raw target DB provenance remained blocked, so the safe high-value advance was proving API drilldown readiness from existing visual contract evidence instead of mutation. The real packet verifies `381` elements, `132` nodes, `249` edges, `70` DJs, `51` events, `11` venues, route/detail/neighbor/search samples `5/12/12/8`, and `16` cluster filters.
- Focused verification passed: `python -m py_compile tools\stage7_rewrite\scripts\build_atlas_social_manual_participant_visual_api_drilldown.py`; `python -m pytest tools\stage7_rewrite\tests\test_build_atlas_social_manual_participant_visual_api_drilldown.py -q` -> `6 passed`; combined visual-api/visual-smoke/visual-export/graph-search pytest -> `21 passed`; strict URL/key/path grep returned no hits.

2026-05-26 atlas T6/T5 manual participant visual UI/API smoke addition:

- Added `tools\stage7_rewrite\scripts\build_atlas_social_manual_participant_visual_smoke.py` and `tools\stage7_rewrite\tests\test_build_atlas_social_manual_participant_visual_smoke.py`.
- Output packet: `reports\ATLAS_T6_MANUAL_PARTICIPANT_VISUAL_SMOKE_20260526.md`; machine outputs under `tools\stage7_rewrite\reports\atlas_social_manual_participant_visual_smoke_q6_20260526`.
- The script is report-only. It consumes the 09:54 visual graph, cluster rows, search drilldown, and graph-window rollup, emits a UI/API contract and Cytoscape elements, validates duplicate/dangling/search/window coverage, and keeps all acceptance/write/public gates closed.
- LLM audit: source/raw target DB provenance remained blocked, so the safe high-value advance was proving consumer contract readiness instead of mutation. The real packet verifies `132` nodes, `249` edges, `381` Cytoscape elements, `70` DJs, `51` events, `11` venues, `121` search rows, and `70` graph-window seeds.
- Focused verification passed: `python -m py_compile tools\stage7_rewrite\scripts\build_atlas_social_manual_participant_visual_smoke.py`; `python -m pytest tools\stage7_rewrite\tests\test_build_atlas_social_manual_participant_visual_smoke.py -q` -> `5 passed`; combined visual-smoke/visual-export/graph-search pytest -> `15 passed`; strict URL/key/path grep returned no hits.

2026-05-26 atlas T6/T5 manual participant visual export addition:

- Added `tools\stage7_rewrite\scripts\build_atlas_social_manual_participant_visual_export.py` and `tools\stage7_rewrite\tests\test_build_atlas_social_manual_participant_visual_export.py`.
- Output packet: `reports\ATLAS_T6_MANUAL_PARTICIPANT_VISUAL_EXPORT_20260526.md`; machine outputs under `tools\stage7_rewrite\reports\atlas_social_manual_participant_visual_export_q6_20260526`.
- The script is report-only. It consumes the `16` graph/search consistency-ready rows, opens selected serving SQLite read-only, emits a local visualization graph, cluster drilldown, search drilldown, graph-window rollup, and keeps all acceptance/write/public gates closed.
- LLM audit: source/raw target DB provenance remained blocked, so the safe high-value advance was local visualization/search export instead of mutation. The real packet verifies `51` selected events, `70` DJs, `11` venues, `249` visual edges, `121` search drilldown rows, and `70` graph windows.
- Focused verification passed: `python -m py_compile tools\stage7_rewrite\scripts\build_atlas_social_manual_participant_visual_export.py`; `python -m pytest tools\stage7_rewrite\tests\test_build_atlas_social_manual_participant_visual_export.py -q` -> `5 passed`; combined visual/graph/readback pytest -> `17 passed`; strict URL/key/path grep returned no hits.

2026-05-26 atlas T6/T5 manual participant graph/search consistency addition:

- Added `tools\stage7_rewrite\scripts\build_atlas_social_manual_participant_graph_search_consistency.py` and `tools\stage7_rewrite\tests\test_build_atlas_social_manual_participant_graph_search_consistency.py`.
- Output packet: `reports\ATLAS_T6_MANUAL_PARTICIPANT_GRAPH_SEARCH_CONSISTENCY_20260526.md`; machine outputs under `tools\stage7_rewrite\reports\atlas_social_manual_participant_graph_search_consistency_q6_20260526`.
- The script is report-only. It consumes the `16` readback-ready rows, opens selected serving SQLite read-only, streams the local full relation bundle, validates serving/search/graph-window/bundle coverage, emits `16` ready rows and `0` blocked rows, and keeps all acceptance/write/public gates closed.
- LLM audit: source/raw target DB provenance remained blocked, so the safe high-value advance was local graph/search consistency validation instead of mutation. The real packet verifies `51` events, `198` DJ-event edges, `70` DJ ids, search docs `51/70`, graph-window DJ seeds `70`, and bundle coverage `51/70/198/51`.
- Focused verification passed: `python -m py_compile tools\stage7_rewrite\scripts\build_atlas_social_manual_participant_graph_search_consistency.py`; `python -m pytest tools\stage7_rewrite\tests\test_build_atlas_social_manual_participant_graph_search_consistency.py -q` -> `5 passed`; combined graph/readback/bundle pytest -> `15 passed`; strict URL/key/path grep returned no hits.

2026-05-26 atlas T6 manual participant event-identity readback gate addition:

- Added `tools\stage7_rewrite\scripts\build_atlas_social_manual_participant_event_identity_readback_gate.py` and `tools\stage7_rewrite\tests\test_build_atlas_social_manual_participant_event_identity_readback_gate.py`.
- Output packet: `reports\ATLAS_T6_MANUAL_PARTICIPANT_EVENT_IDENTITY_READBACK_GATE_20260526.md`; machine outputs under `tools\stage7_rewrite\reports\atlas_social_manual_participant_event_identity_readback_gate_q6_20260526`.
- The script is report-only. It consumes the `16` deduped event-identity candidates, opens selected serving SQLite read-only, validates selectors/source/event/participant evidence, emits `16` ready rows and `0` blocked rows, and keeps all acceptance/write/public gates closed.
- LLM audit: the correct advance after the 08:43 event-identity packet was DB-backed readback, not source/raw DB mutation. The first real run over-blocked `5` venue-alias rows; readback venue normalization now handles `OIL CLUB`, `OIL Mainroom`, and `Dada Kunming & 桠雀`.
- Focused verification passed: `python -m py_compile tools\stage7_rewrite\scripts\build_atlas_social_manual_participant_event_identity_readback_gate.py`; `python -m pytest tools\stage7_rewrite\tests\test_build_atlas_social_manual_participant_event_identity_readback_gate.py -q` -> `7 passed`; combined Q6 focused pytest -> `49 passed`; row-count check `16/16/16/0/10/6/51`; strict URL/key grep returned no hits.

2026-05-26 atlas T6 manual participant event-identity resolution packet addition:

- Added `tools\stage7_rewrite\scripts\build_atlas_social_manual_participant_event_identity_resolution_packet.py` and `tools\stage7_rewrite\tests\test_build_atlas_social_manual_participant_event_identity_resolution_packet.py`.
- Output packet: `reports\ATLAS_T6_MANUAL_PARTICIPANT_EVENT_IDENTITY_RESOLUTION_PACKET_20260526.md`; machine outputs under `tools\stage7_rewrite\reports\atlas_social_manual_participant_event_identity_resolution_q6_20260526`.
- The script is report-only. It consumes the 31 manual event-identity work orders, derives deterministic date and venue-alias resolution candidates, emits 18 candidate rows / 16 deduped rows / 13 still-blocked rows, and keeps all acceptance/write/public gates closed.
- LLM audit: source/OCR remained blocked by missing OCR/Markdown, so the useful safe lane was manual event-identity resolution. The packet is not graph fact acceptance and not serving rebuild authorization.
- LLM self-correction: focused tests exposed a real multi-venue alias bug where `THE BOX ... DADA BEIJING` could be treated as `dada_beijing`; canonicalization now detects multi-venue context before Dada alias matching.
- Focused verification passed: `python -m py_compile tools\stage7_rewrite\scripts\build_atlas_social_manual_participant_event_identity_resolution_packet.py`; `python -m pytest tools\stage7_rewrite\tests\test_build_atlas_social_manual_participant_event_identity_resolution_packet.py -q` -> `5 passed`; combined Q6 focused pytest -> `42 passed`; row-count check `31/18/16/12/6/13/2`; strict URL/key grep returned no hits.

2026-05-26 atlas T6 manual participant source/OCR localization probe addition:

- Added `tools\stage7_rewrite\scripts\probe_atlas_social_manual_participant_source_ocr_localization.py` and `tools\stage7_rewrite\tests\test_probe_atlas_social_manual_participant_source_ocr_localization.py`.
- Output packet: `reports\ATLAS_T6_MANUAL_PARTICIPANT_SOURCE_OCR_LOCALIZATION_PROBE_20260526.md`; machine outputs under `tools\stage7_rewrite\reports\atlas_social_manual_participant_source_ocr_localization_q6_20260526`.
- The script is report-only. It consumes the single Q6 `source_ocr_recovery` work order, reads existing local source/OCR evidence read-only, and emits blocked rows plus OCR/Markdown-missing queues while keeping acceptance/write/public gates closed.
- LLM audit: the correct advance after blocker recovery is local artifact localization, not repeating the DB provenance blocker. The row has local source DB/source-url/exact-date evidence, but no OCR/Markdown candidate yet.
- Focused verification passed: `python -m py_compile tools\stage7_rewrite\scripts\probe_atlas_social_manual_participant_source_ocr_localization.py`; `python -m pytest tools\stage7_rewrite\tests\test_probe_atlas_social_manual_participant_source_ocr_localization.py -q` -> `2 passed`; real summary JSON parsed.

2026-05-26 atlas T6 manual participant blocker recovery packet addition:

- Added `tools\stage7_rewrite\scripts\build_atlas_social_manual_participant_blocker_recovery_packet.py` and `tools\stage7_rewrite\tests\test_build_atlas_social_manual_participant_blocker_recovery_packet.py`.
- Output packet: `reports\ATLAS_T6_MANUAL_PARTICIPANT_BLOCKER_RECOVERY_PACKET_20260526.md`; machine outputs under `tools\stage7_rewrite\reports\atlas_social_manual_participant_blocker_recovery_q6_20260526`.
- The script is report-only. It consumes existing redacted blocker rows from the source-context, acceptance-precheck, and event-cluster packets, collapses the duplicate source/OCR row, and emits `38` recovery work orders split into source/OCR `1`, manual event-match `4`, event-evidence repair `2`, and manual event-identity `31`.
- LLM audit: this is the correct pivot after the target DB provenance blocker; it advances recovery queues without inferring a source/raw DB target or opening any DB.
- Focused verification passed: `python -m py_compile tools\stage7_rewrite\scripts\build_atlas_social_manual_participant_blocker_recovery_packet.py`; `python -m pytest tools\stage7_rewrite\tests\test_build_atlas_social_manual_participant_blocker_recovery_packet.py -q` -> `4 passed`; combined Q6 focused pytest -> `45 passed`; row-count check `38/31/4/2/1`; strict URL/key grep returned no hits.

2026-05-26 atlas T6 manual participant target DB provenance packet addition:

- Added `tools\stage7_rewrite\scripts\build_atlas_social_manual_participant_target_db_provenance_packet.py` and `tools\stage7_rewrite\tests\test_build_atlas_social_manual_participant_target_db_provenance_packet.py`.
- Output packet: `reports\ATLAS_T6_MANUAL_PARTICIPANT_TARGET_DB_PROVENANCE_20260526.md`; machine outputs under `tools\stage7_rewrite\reports\atlas_social_manual_participant_target_db_provenance_q6_20260526`.
- The script is report-only. It audits current SSOT/upstream evidence for a source/raw target DB and blocks all `46` real-snapshot rows because direct existing explicit target DB paths remain `0`. It classifies serving read-model refs as rejected and source DB refs as not bound to the Q6 gate.
- LLM audit: this prevents an unsafe inference from historical source DB refs or selected serving SQLite into a source/raw write target. The next gate needs direct upstream provenance before any real snapshot or write confirmation.
- Focused verification passed: `python -m py_compile tools\stage7_rewrite\scripts\build_atlas_social_manual_participant_target_db_provenance_packet.py`; `python -m pytest tools\stage7_rewrite\tests\test_build_atlas_social_manual_participant_target_db_provenance_packet.py -q` -> `4 passed`; combined Q6 focused pytest -> `26 passed`; report/output leak grep returned no hits.

2026-05-26 atlas T6 manual participant DB real snapshot gate addition:

- Added `tools\stage7_rewrite\scripts\build_atlas_social_manual_participant_db_real_snapshot_gate.py` and `tools\stage7_rewrite\tests\test_build_atlas_social_manual_participant_db_real_snapshot_gate.py`.
- Output packet: `reports\ATLAS_T6_MANUAL_PARTICIPANT_DB_REAL_SNAPSHOT_GATE_20260526.md`; machine outputs under `tools\stage7_rewrite\reports\atlas_social_manual_participant_db_real_snapshot_gate_q6_20260526`.
- The script is report-only. Without an explicit `--target-db`, it blocks all `46` prewrite snapshot rows, emits `0` real snapshot rows, keeps explicit target DB present/opened read-only at `0/0`, and leaves accepted_for_graph/source_sqlite_write/serving_rebuild/graph_write/public_serving_field/memory rows at `0`.
- LLM audit: this prevents an unsafe jump from selected serving SQLite read-model evidence to source/raw DB mutation. The next gate must identify an explicit source/raw target DB path before any real snapshot or write confirmation.
- Focused verification passed: `python -m py_compile tools\stage7_rewrite\scripts\build_atlas_social_manual_participant_db_real_snapshot_gate.py`; `python -m pytest tools\stage7_rewrite\tests\test_build_atlas_social_manual_participant_db_real_snapshot_gate.py -q` -> `4 passed`; combined Q6 focused pytest -> `22 passed`.

2026-05-26 atlas T6 manual participant DB prewrite snapshot packet addition:

- Added `tools\stage7_rewrite\scripts\build_atlas_social_manual_participant_db_prewrite_snapshot_packet.py` and `tools\stage7_rewrite\tests\test_build_atlas_social_manual_participant_db_prewrite_snapshot_packet.py`.
- Output packet: `reports\ATLAS_T6_MANUAL_PARTICIPANT_DB_PREWRITE_SNAPSHOT_PACKET_20260526.md`; machine outputs under `tools\stage7_rewrite\reports\atlas_social_manual_participant_db_prewrite_snapshot_q6_20260526`.
- The script is report-only. It consumes `46` DB write-gate target rows, emits `46` prewrite snapshot rows plus a manifest, keeps blocked rows at `0`, contract row hashes at `46`, duplicate hashes at `0`, and leaves accepted_for_graph/source_sqlite_write/serving_rebuild/graph_write/public_serving_field/memory rows at `0`.
- LLM audit: this improves safety by materializing the prewrite contract snapshot, but it still does not open the source/raw DB. A future confirmed writer must capture real read-only DB row snapshots before any write confirmation.
- Focused verification passed: `python -m py_compile tools\stage7_rewrite\scripts\build_atlas_social_manual_participant_db_prewrite_snapshot_packet.py`; `python -m pytest tools\stage7_rewrite\tests\test_build_atlas_social_manual_participant_db_prewrite_snapshot_packet.py -q` -> `4 passed`; combined Q6 focused pytest -> `18 passed`.

2026-05-26 atlas T6 manual participant DB write-gate contract addition:

- Added `tools\stage7_rewrite\scripts\build_atlas_social_manual_participant_db_write_gate_packet.py` and `tools\stage7_rewrite\tests\test_build_atlas_social_manual_participant_db_write_gate_packet.py`.
- Output packet: `reports\ATLAS_T6_MANUAL_PARTICIPANT_DB_WRITE_GATE_20260526.md`; machine outputs under `tools\stage7_rewrite\reports\atlas_social_manual_participant_db_write_gate_q6_20260526`.
- The script is report-only. It consumes `46` readback-preflight ready rows, emits `46` write-gate target rows plus dry-run work orders, rollback contracts, and postwrite readback contracts, carries forward `5` duplicate selector evidence rows, and leaves accepted_for_graph/source_sqlite_write/serving_rebuild/graph_write/public_serving_field/memory rows at `0`.
- LLM self-correction: focused tests exposed a real zero-value parsing bug where `readback_blocked_rows=0` was treated as missing by an `or -1` fallback. The parser now treats valid zero counts explicitly.
- Focused verification passed: `python -m py_compile tools\stage7_rewrite\scripts\build_atlas_social_manual_participant_db_write_gate_packet.py`; `python -m pytest tools\stage7_rewrite\tests\test_build_atlas_social_manual_participant_db_write_gate_packet.py -q` -> `5 passed`; combined Q6 focused pytest -> `14 passed`.

2026-05-26 atlas T6 manual participant readback preflight addition:

- Added `tools\stage7_rewrite\scripts\build_atlas_social_manual_participant_readback_preflight_packet.py` and `tools\stage7_rewrite\tests\test_build_atlas_social_manual_participant_readback_preflight_packet.py`.
- Output packet: `reports\ATLAS_T6_MANUAL_PARTICIPANT_READBACK_PREFLIGHT_20260526.md`; machine outputs under `tools\stage7_rewrite\reports\atlas_social_manual_participant_readback_preflight_q6_20260526`.
- The script is report-only. It opens selected serving SQLite in read-only mode, validates `46` consolidation selectors across `199` unique event IDs, emits `46` write-preflight ready report-only rows and `0` blocked rows, carries forward `5` duplicate selector evidence rows, and leaves accepted_for_graph/source_sqlite_write/serving_rebuild/graph_write/public_serving_field/memory rows at `0`.
- LLM self-correction: the first real run over-blocked equivalent source refs because not every ref shared the selected `source_hash`; the script now requires the expected hash to appear in the evidence set and records non-identical equivalent hashes as warnings. Build metadata path-like strings are sanitized before leak scanning.
- Focused verification passed: `python -m py_compile tools\stage7_rewrite\scripts\build_atlas_social_manual_participant_readback_preflight_packet.py`; `python -m pytest tools\stage7_rewrite\tests\test_build_atlas_social_manual_participant_readback_preflight_packet.py -q` -> `4 passed`; combined Q6 focused pytest -> `9 passed`.

2026-05-26 atlas T6 manual participant consolidation gate packet addition:

- Added `tools\stage7_rewrite\scripts\build_atlas_social_manual_participant_consolidation_gate_packet.py` and `tools\stage7_rewrite\tests\test_build_atlas_social_manual_participant_consolidation_gate_packet.py`.
- Output packet: `reports\ATLAS_T6_MANUAL_PARTICIPANT_CONSOLIDATION_GATE_PACKET_20260526.md`; machine outputs under `tools\stage7_rewrite\reports\atlas_social_manual_participant_consolidation_gate_q6_20260526`.
- The script is report-only. It consumes event-id and semantic cluster consolidation candidates, emits `51` gate targets, collapses `5` duplicate selector rows, leaves `46` deduped manual DB readback targets split `27/19`, and leaves accepted_for_graph/source_sqlite_write/serving_rebuild/graph_write/public_serving_field/memory rows at `0`.
- Focused verification passed: `python -m py_compile tools\stage7_rewrite\scripts\build_atlas_social_manual_participant_consolidation_gate_packet.py`; `python -m pytest tools\stage7_rewrite\tests\test_build_atlas_social_manual_participant_consolidation_gate_packet.py -q` -> `5 passed`; combined Q6 focused pytest -> `26 passed`.

2026-05-26 atlas T6 manual participant event-cluster review addition:

- Added `tools\stage7_rewrite\scripts\build_atlas_social_manual_participant_event_cluster_review.py` and `tools\stage7_rewrite\tests\test_build_atlas_social_manual_participant_event_cluster_review.py`.
- Output packet: `reports\ATLAS_T6_MANUAL_PARTICIPANT_EVENT_CLUSTER_REVIEW_20260526.md`; machine outputs under `tools\stage7_rewrite\reports\atlas_social_manual_participant_event_cluster_review_q6_20260526`.
- The script is report-only. It consumes the 05:55 event-id dedupe and ambiguous event-cluster rows, separates event-id consolidation candidates from semantic cluster consolidation candidates and manually blocked event-identity rows, and leaves accepted_for_graph/source_sqlite_write/serving_rebuild/graph_write/public_serving_field/memory rows at `0`.
- Focused verification passed: `python -m py_compile tools\stage7_rewrite\scripts\build_atlas_social_manual_participant_event_cluster_review.py`; `python -m pytest tools\stage7_rewrite\tests\test_build_atlas_social_manual_participant_event_cluster_review.py -q` -> `5 passed`; combined Q6 focused pytest -> `21 passed`.

2026-05-26 atlas T6 manual participant acceptance precheck addition:

- Added `tools\stage7_rewrite\scripts\build_atlas_social_manual_participant_acceptance_precheck.py` and `tools\stage7_rewrite\tests\test_build_atlas_social_manual_participant_acceptance_precheck.py`.
- Output packet: `reports\ATLAS_T6_MANUAL_PARTICIPANT_ACCEPTANCE_PRECHECK_20260526.md`; machine outputs under `tools\stage7_rewrite\reports\atlas_social_manual_participant_acceptance_precheck_q6_20260526`.
- The script is report-only. It consumes the 05:36 deterministic precheck candidates, separates strict-ready rows from semantic duplicate event-id dedupe rows, ambiguous event-cluster rows, and blocked event-evidence rows, and leaves accepted_for_graph/source_sqlite_write/serving_rebuild/graph_write/public_serving_field/memory rows at `0`.
- Focused verification passed: `python -m py_compile tools\stage7_rewrite\scripts\build_atlas_social_manual_participant_acceptance_precheck.py`; `python -m pytest tools\stage7_rewrite\tests\test_build_atlas_social_manual_participant_acceptance_precheck.py -q` -> `6 passed`; combined Q6 focused pytest -> `16 passed`.

2026-05-26 atlas T6 manual participant source-context review addition:

- Added `tools\stage7_rewrite\scripts\build_atlas_social_manual_participant_source_context_review.py` and `tools\stage7_rewrite\tests\test_build_atlas_social_manual_participant_source_context_review.py`.
- Output packet: `reports\ATLAS_T6_MANUAL_PARTICIPANT_SOURCE_CONTEXT_REVIEW_20260526.md`; machine outputs under `tools\stage7_rewrite\reports\atlas_social_manual_participant_source_context_review_q6_20260526`.
- The script is report-only. It consumes the 05:24 manual participant work orders and source-account batches, reads the selected serving SQLite in read-only mode, and emits deterministic acceptance precheck candidates plus blocked/source-OCR recovery rows. It leaves source/raw Atlas DB mutation, serving SQLite rebuild/write, public pointer, Neo4j/Qdrant/SQLite production writes, deploy/upload/review, memory, network/model/paid API, secret reads, 9router, and D: root scans false.
- Focused verification passed: `python -m py_compile tools\stage7_rewrite\scripts\build_atlas_social_manual_participant_source_context_review.py`; `python -m pytest tools\stage7_rewrite\tests\test_build_atlas_social_manual_participant_source_context_review.py -q` -> `4 passed`; combined Q6 focused pytest -> `10 passed`.

2026-05-26 atlas T6 manual participant review triage addition:

- Added `tools\stage7_rewrite\scripts\build_atlas_social_manual_participant_review_triage.py` and `tools\stage7_rewrite\tests\test_build_atlas_social_manual_participant_review_triage.py`.
- Output packet: `reports\ATLAS_T6_MANUAL_PARTICIPANT_REVIEW_TRIAGE_20260526.md`; machine outputs under `tools\stage7_rewrite\reports\atlas_social_manual_participant_review_triage_q6_20260526`.
- The script is report-only. It consumes the 114 manual participant review candidates from the Q6 broader recovery acceptance gate, emits participant review work orders and source-account batch queues, and leaves source/raw Atlas DB mutation, serving SQLite rebuild/write, public pointer, Neo4j/Qdrant/SQLite production writes, deploy/upload/review, memory, network/model/paid API, secret reads, 9router, and D: root scans false.
- Focused verification passed: `python -m py_compile tools\stage7_rewrite\scripts\build_atlas_social_manual_participant_review_triage.py`; `python -m pytest tools\stage7_rewrite\tests\test_build_atlas_social_manual_participant_review_triage.py -q` -> `3 passed`.

2026-05-26 atlas T6 broader recovery acceptance gate addition:

- Added `tools\stage7_rewrite\scripts\build_atlas_social_broader_recovery_acceptance_gate.py` and `tools\stage7_rewrite\tests\test_build_atlas_social_broader_recovery_acceptance_gate.py`.
- Output packet: `reports\ATLAS_T6_BROADER_RECOVERY_ACCEPTANCE_GATE_20260526.md`; machine outputs under `tools\stage7_rewrite\reports\atlas_social_broader_recovery_acceptance_gate_q6_20260526`.
- The script is report-only. It consumes the Q6 broader recovery combined review slice, emits manual participant review candidates and blocked rows, and leaves source/raw Atlas DB mutation, serving SQLite rebuild/write, public pointer, Neo4j/Qdrant/SQLite production writes, deploy/upload/review, memory, network/model/paid API, secret reads, 9router, and D: root scans false.
- Focused verification passed: `python -m py_compile tools\stage7_rewrite\scripts\build_atlas_social_broader_recovery_acceptance_gate.py`; `python -m pytest tools\stage7_rewrite\tests\test_build_atlas_social_broader_recovery_acceptance_gate.py -q` -> `3 passed`.

2026-05-26 atlas T6 broader source-context recovery addition:

- Added `tools\stage7_rewrite\scripts\build_atlas_social_broader_source_context_recovery_packet.py` and `tools\stage7_rewrite\tests\test_build_atlas_social_broader_source_context_recovery_packet.py`.
- Output packet: `reports\ATLAS_T6_BROADER_SOURCE_CONTEXT_RECOVERY_PACKET_20260526.md`; machine outputs under `tools\stage7_rewrite\reports\atlas_social_broader_source_context_recovery_q6_20260526`.
- The script is report-only. It consumes current T5 source-context/OCR/participant repair work orders, emits bounded review slices and source-account priority rows, and leaves source/raw Atlas DB mutation, serving SQLite rebuild/write, public pointer, Neo4j/Qdrant/SQLite production writes, deploy/upload/review, memory, network/model/paid API, secret reads, 9router, and D: root scans false.
- Focused verification passed: `python -m py_compile tools\stage7_rewrite\scripts\build_atlas_social_broader_source_context_recovery_packet.py`; `python -m pytest tools\stage7_rewrite\tests\test_build_atlas_social_broader_source_context_recovery_packet.py -q` -> `2 passed`.

2026-05-25 T1 source-intake static diagnostic addition:

- Added `tools\stage7_rewrite\scripts\build_t1_source_intake_static_diagnostic.py` and `tools\stage7_rewrite\tests\test_build_t1_source_intake_static_diagnostic.py`.
- Output packet: `reports\ATLAS_T1_SOURCE_INTAKE_STATIC_DIAGNOSTIC_20260525.md`; machine summary `reports\t1_source_intake_static_diagnostic_20260525_2218\summary.json`.
- The script is report-only/no-secret. It reads registry plus existing repo-local queue refresh validation evidence, classifies freshness for T2/T4 handoff, and does not call exporter, read cookie/env secret values, scan D: roots, deploy, upload/review, or mutate Atlas DB/graph/vector/production state.
- Focused verification passed: `python -m py_compile tools\stage7_rewrite\scripts\build_t1_source_intake_static_diagnostic.py`; `python -m pytest tools\stage7_rewrite\tests\test_build_t1_source_intake_static_diagnostic.py -q` -> `2 passed`.
- Current risk remains closed: previous queue refresh was effective but stale, so a fresh no-secret exporter/session gate is required before the next T2/T4 source refresh.

2026-05-25 atlas T5 venue acceptance gate addition:

- Added `tools\stage7_rewrite\scripts\build_atlas_dj_venue_acceptance_gate.py` and `tools\stage7_rewrite\tests\test_build_atlas_dj_venue_acceptance_gate.py`.
- Output packet: `reports\ATLAS_T5_VENUE_ACCEPTANCE_GATE_20260525.md`; machine outputs under `reports\atlas_dj_venue_acceptance_gate_activity_current_20260525_1809`.
- The script is report-only. It consumes venue auto candidates, checks source/serving SQLite through read-only connections, and emits all/patch/blocked JSONL without source DB mutation, serving write/rebuild, public pointer/deploy, graph/vector/production write, upload/review, memory, network/model/paid API, secret reads, 9router use, or D: root scans.
- Focused verification passed: `python -m py_compile tools\stage7_rewrite\scripts\build_atlas_dj_venue_acceptance_gate.py`; `python -m pytest tools\stage7_rewrite\tests\test_build_atlas_dj_venue_acceptance_gate.py -q` -> `1 passed`.
- Current production risk remains closed: this gate produced `0` patch candidates and `304` blocked rows, so any future serving change needs a separate conflict-review or rebuild gate.

## Current facts

| Area | Count |
|---|---:|
| package scripts | 50 |
| CLI commands | 26 |
| TS source files | 84 |
| TS test files | 60 |
| Stage7 Python test files | 7 |
| desktop/PCUI files | 37 |
| tools files | 36 |
| model/runtime profiles | 4 |
| prompt files | 16 |

2026-05-25 atlas T6 YYYY identity acceptance gate addition:

- Added `tools\stage7_rewrite\scripts\build_atlas_social_yyyy_identity_acceptance_gate.py` and `tools\stage7_rewrite\tests\test_build_atlas_social_yyyy_identity_acceptance_gate.py`.
- Output packet: `reports\ATLAS_T6_YYYY_IDENTITY_ACCEPTANCE_GATE_20260525.md`; machine outputs under `tools\stage7_rewrite\reports\atlas_social_yyyy_identity_acceptance_q6_20260525`.
- The script is report-only. It consumes the accepted `YYYY` source-context row plus rendered public profile evidence, marks `YYYY` as a staging-review identity candidate, and leaves identity proof promotion, avatar display, public serving fields, graph writes, Neo4j/Qdrant/SQLite, deploy/upload/review, memory, model/paid API, secret reads, and D: root scans false.
- Focused verification passed: `python -m py_compile tools\stage7_rewrite\scripts\build_atlas_social_yyyy_identity_acceptance_gate.py`; `python -m pytest tools\stage7_rewrite\tests\test_build_atlas_social_yyyy_identity_acceptance_gate.py -q` -> `2 passed`.

2026-05-25 atlas T6 blocked source-context acceptance review addition:

- Added `tools\stage7_rewrite\scripts\build_atlas_social_blocked_source_context_acceptance_review.py` and `tools\stage7_rewrite\tests\test_build_atlas_social_blocked_source_context_acceptance_review.py`.
- Output packet: `reports\ATLAS_T6_BLOCKED_SOURCE_CONTEXT_ACCEPTANCE_REVIEW_20260525.md`; machine outputs under `tools\stage7_rewrite\reports\atlas_social_blocked_source_context_acceptance_q6_20260525`.
- The script is report-only. It consumes the Q6 blocked source-context follow-up rows/candidates, accepts `YYYY` as source-context-ready for a future identity-review gate, leaves `Cod.Act` blocked without local source context, and leaves identity proof, avatar display, public serving fields, graph writes, Neo4j/Qdrant/SQLite, deploy/upload/review, memory, network/model/paid API, secret reads, and D: root scans false.
- Focused verification passed: `python -m py_compile tools\stage7_rewrite\scripts\build_atlas_social_blocked_source_context_acceptance_review.py`; `python -m pytest tools\stage7_rewrite\tests\test_build_atlas_social_blocked_source_context_acceptance_review.py -q` -> `2 passed`.

2026-05-25 atlas T6 blocked source-context follow-up addition:

- Added `tools\stage7_rewrite\scripts\build_atlas_social_blocked_source_context_followup.py` and `tools\stage7_rewrite\tests\test_build_atlas_social_blocked_source_context_followup.py`.
- Output packet: `reports\ATLAS_T6_BLOCKED_SOURCE_CONTEXT_FOLLOWUP_20260525.md`; machine outputs under `tools\stage7_rewrite\reports\atlas_social_blocked_source_context_followup_q6_20260525`.
- The script is report-only. It consumes the Q6 identity acceptance blocked rows and bounded repo-local Atlas sidecar files, finds exact local source-context candidates for `YYYY`, leaves `Cod.Act` blocked without context, and leaves identity proof, avatar display, public serving fields, graph writes, Neo4j/Qdrant/SQLite, deploy/upload/review, memory, network/model/paid API, secret reads, and D: root scans false.
- Focused verification passed: `python -m py_compile tools\stage7_rewrite\scripts\build_atlas_social_blocked_source_context_followup.py`; `python -m pytest tools\stage7_rewrite\tests\test_build_atlas_social_blocked_source_context_followup.py -q` -> `3 passed`.

2026-05-25 atlas Q5/Q6 product-truth mutation packet addition:

- Added `tools\stage7_rewrite\scripts\build_atlas_social_product_truth_mutation_packet.py` and `tools\stage7_rewrite\tests\test_build_atlas_social_product_truth_mutation_packet.py`.
- Output packet: `reports\ATLAS_Q5_Q6_PRODUCT_TRUTH_MUTATION_PACKET_20260525.md`; machine outputs under `tools\stage7_rewrite\reports\atlas_social_product_truth_mutation_packet_q5_q6_20260525`.
- The script is report-only. It consumes the Q5/Q6 product-truth promotion review ready rows and emits exact local Neo4j staging social-profile edge target selectors, planned metadata mutation Cypher, prewrite/postwrite readback Cypher, rollback Cypher, and public-safe execution requirements. It leaves Neo4j writes, production graph labels, identity proof, avatar display, public serving fields, Qdrant, SQLite, public pointer, deploy/upload/review, memory, network/model/paid API, secret read, and D: root scan flags false.
- Focused verification passed: `python -m py_compile tools\stage7_rewrite\scripts\build_atlas_social_product_truth_mutation_packet.py`; `python -m pytest tools\stage7_rewrite\tests\test_build_atlas_social_product_truth_mutation_packet.py -q` -> `3 passed`.

2026-05-24 atlas T6 strict manual acceptance review addition:

- Added `tools\stage7_rewrite\scripts\build_atlas_social_strict_manual_acceptance_review.py` and `tools\stage7_rewrite\tests\test_build_atlas_social_strict_manual_acceptance_review.py`.
- Output packet: `reports\ATLAS_T6_STRICT_MANUAL_ACCEPTANCE_REVIEW_PACKET_20260524.md`; machine outputs under `tools\stage7_rewrite\reports\atlas_social_strict_manual_acceptance_q6_20260524`.
- The script is report-only. It joins the `3` rendered SoundCloud public-profile rows with the `3` manual acceptance rows and emits staging-review accepted identity candidates while leaving accepted_for_graph, identity_proof promotion, avatar display, public serving field, graph_write_allowed, DB/vector/memory/deploy/upload, network/model/paid API, secret read, and D: root scan flags false.
- Focused verification passed: `python -m py_compile tools\stage7_rewrite\scripts\build_atlas_social_strict_manual_acceptance_review.py`; `python -m pytest tools\stage7_rewrite\tests\test_build_atlas_social_strict_manual_acceptance_review.py -q` -> `2 passed`.

2026-05-17 refresh:

- `npm run build` passed.
- Targeted TypeScript verification passed `27` tests.
- Targeted Stage7/weekly Python verification passed `46` tests with `PYTHONPATH=C:\code\githubstar\wechathtmldownload\tools\stage7_rewrite`.
- Safe AST scan of `tools\stage7_rewrite` parsed `450` Python files with `0` syntax errors.
- Stale test-path debt found: `test_full93k_auto_continue.py` and `test_full93k_quality_checkpoint.py` still expect scripts at `tools\stage7_rewrite\scripts\`, while current files are under `tools\stage7_rewrite\scripts\archive_old\`.

2026-05-19 atlas source-lineage addition:

- Added `tools\stage7_rewrite\scripts\build_atlas_full_source_lineage.py` and `tools\stage7_rewrite\tests\test_build_atlas_full_source_lineage.py`.
- Output packet: `tools\stage7_rewrite\reports\atlas_full_source_lineage_47k_93k_gap_20260519\atlas_full_source_lineage.md`.
- The script is read-only and bounded to project script/config roots. It records D:/mnt/d references but does not open or scan D: paths.
- Current production decisions from the packet: `47,340` stays production base; `93k/FULL_MAP` stays upstream lineage; full V6 `81,417` stays candidate-only; P1 residual OCR debt is `99 + 30`; external identity graph edges remain `0`; role-isolated vector alias apply is complete at `tools\stage7_rewrite\reports\qdrant_role_alias_apply_47k_delta375_20260519\qdrant_role_alias_apply_report.md`.

2026-05-19 atlas gap/backfill execution addition:

- Added `tools\stage7_rewrite\scripts\build_atlas_gap_backfill_execution_packet.py` and `tools\stage7_rewrite\tests\test_build_atlas_gap_backfill_execution_packet.py`.
- Output packet: `tools\stage7_rewrite\reports\atlas_gap_backfill_execution_packet_20260519\gap_backfill_execution_packet.md`.
- The script is read-only. It converts the source-lineage packet, gap ledger, and Dajiala ROI gate into `11` actions: `3` no-rerun actions and `8` gate-required hold/backfill actions.

2026-05-19 atlas P3 final-lock addition:

- Added `tools\stage7_rewrite\scripts\build_external_identity_source_context_decision_packet.py` and `tools\stage7_rewrite\tests\test_build_external_identity_source_context_decision_packet.py`.
- Output packets include `tools\stage7_rewrite\reports\external_identity_source_context_decision_47k_delta375_20260519\source_context_decision_summary.md`, `tools\stage7_rewrite\reports\graph_candidate_pack_final_lock_47k_delta375_20260519\graph_candidate_pack_readiness.md`, and `tools\stage7_rewrite\reports\graph_rag_recommendation_current_smoke_47k_delta375_final_lock_20260519\graph_rag_recommendation_current_smoke.md`.
- The P3 final lock keeps external identity graph edges at `0` after source-context decision, public follow-up, and strict review gates.

2026-05-23 atlas serving production execution-packet addition:

- Added `tools\stage7_rewrite\scripts\build_atlas_serving_production_execution_packet.py` and `tools\stage7_rewrite\tests\test_build_atlas_serving_production_execution_packet.py`.
- Output packet: `reports\atlas_serving_production_execution_packet_20260523_2119\atlas_serving_production_execution_packet.md` / `.json`.
- The script is report-only. It verifies the selected field-repair fullcomplete candidate against existing manifest/preflight/API/browser evidence, records rollout, rollback, and post-write remote checks, and leaves serving pointer update, CloudRun/VPS deploy, Neo4j/Qdrant/SQLite production write, mini-program upload/review, memory write, secret read, paid API, and D: root scan flags false.
- Focused verification passed: `python -m py_compile tools\stage7_rewrite\scripts\build_atlas_serving_production_execution_packet.py`; `python -m pytest tools\stage7_rewrite\tests\test_build_atlas_serving_production_execution_packet.py -q` -> `2 passed`.

2026-05-23 atlas T6 top-review triage addition:

- Added `tools\stage7_rewrite\scripts\build_atlas_social_outlink_top_review_triage.py` and `tools\stage7_rewrite\tests\test_build_atlas_social_outlink_top_review_triage.py`.
- Output packet: `reports\ATLAS_T6_OUTLINK_TOP_REVIEW_TRIAGE_20260523.md`; machine outputs under `tools\stage7_rewrite\reports\atlas_social_outlink_top_review_triage_q6_20260523_2225`.
- The script is report-only. It converts the `80`-row top-review queue into a `12`-row candidate-only bounded fetch plan and leaves accepted_for_graph, identity_proof promotion, graph_write_allowed, network/model/paid API, DB/vector/memory/deploy/upload, secret read, and D: root scan flags false.
- Focused verification passed: `python -m py_compile tools\stage7_rewrite\scripts\build_atlas_social_outlink_top_review_triage.py`; `python -m pytest tools\stage7_rewrite\tests\test_build_atlas_social_outlink_top_review_triage.py -q` -> `2 passed`.

2026-05-24 atlas T6 rendered profile evidence addition:

- Added `tools\stage7_rewrite\scripts\build_atlas_social_rendered_profile_evidence_packet.py` and `tools\stage7_rewrite\tests\test_build_atlas_social_rendered_profile_evidence_packet.py`.
- Output packet: `reports\ATLAS_T6_RENDERED_PROFILE_EVIDENCE_PACKET_20260524.md`; machine outputs under `tools\stage7_rewrite\reports\atlas_social_rendered_profile_evidence_q6_20260524_0328`.
- The script is report-only. It uses OpenCLI to render the `3` manual acceptance-review-ready SoundCloud profile rows, stores sanitized metadata/hash evidence, and leaves accepted_for_graph, identity_proof promotion, avatar display, public serving field, graph_write_allowed, DB/vector/memory/deploy/upload, model/paid API, secret read, and D: root scan flags false.
- Focused verification passed: `python -m py_compile tools\stage7_rewrite\scripts\build_atlas_social_rendered_profile_evidence_packet.py`; `python -m pytest tools\stage7_rewrite\tests\test_build_atlas_social_rendered_profile_evidence_packet.py -q` -> `2 passed`.

2026-05-24 atlas T6 identity-review criteria addition:

- Added `tools\stage7_rewrite\scripts\build_atlas_social_identity_review_criteria.py` and `tools\stage7_rewrite\tests\test_build_atlas_social_identity_review_criteria.py`.
- Output packet: `reports\ATLAS_T6_IDENTITY_REVIEW_CRITERIA_PACKET_20260524.md`; machine outputs under `tools\stage7_rewrite\reports\atlas_social_identity_review_criteria_q6_20260524_0028`.
- The script is report-only. It converts the `12` bounded-fetch SoundCloud metadata rows into `10` deduped T5/T7 manual-review rows / `5` entity rollups and leaves accepted_for_graph, identity_proof promotion, graph_write_allowed, network/model/paid API, body persistence, DB/vector/memory/deploy/upload, secret read, and D: root scan flags false.
- Focused verification passed: `python -m py_compile tools\stage7_rewrite\scripts\build_atlas_social_identity_review_criteria.py`; `python -m pytest tools\stage7_rewrite\tests\test_build_atlas_social_identity_review_criteria.py -q` -> `2 passed`.

2026-05-24 atlas T6 identity source-context review addition:

- Added `tools\stage7_rewrite\scripts\build_atlas_social_identity_source_context_review.py` and `tools\stage7_rewrite\tests\test_build_atlas_social_identity_source_context_review.py`.
- Output packet: `reports\ATLAS_T6_IDENTITY_SOURCE_CONTEXT_REVIEW_20260524.md`; machine outputs under `tools\stage7_rewrite\reports\atlas_social_identity_source_context_review_q6_20260524_0124`.
- The script is report-only. It reads the `5` T5/T7 identity-review entity rollups and the selected Atlas serving SQLite read-only, finds local Atlas source/event context for `3` entities, keeps `2` entities needing Atlas source context, and leaves accepted_for_graph, identity_proof promotion, graph_write_allowed, network/model/paid API, body persistence, DB/vector/memory/deploy/upload, secret read, and D: root scan flags false.
- Focused verification passed: `python -m py_compile tools\stage7_rewrite\scripts\build_atlas_social_identity_source_context_review.py`; `python -m pytest tools\stage7_rewrite\tests\test_build_atlas_social_identity_source_context_review.py -q` -> `2 passed`.

2026-05-24 atlas T6 identity acceptance-gate addition:

- Added `tools\stage7_rewrite\scripts\build_atlas_social_identity_acceptance_gate.py` and `tools\stage7_rewrite\tests\test_build_atlas_social_identity_acceptance_gate.py`.
- Output packet: `reports\ATLAS_T6_IDENTITY_ACCEPTANCE_GATE_PACKET_20260524.md`; machine outputs under `tools\stage7_rewrite\reports\atlas_social_identity_acceptance_gate_q6_20260524_0224`.
- The script is report-only. It converts the `5` source-context review rows into `3` manual acceptance-review-ready rows and `2` blocked rows, while leaving accepted_for_graph, identity_proof promotion, avatar display, public serving field, graph_write_allowed, network/model/paid API, body persistence, DB/vector/memory/deploy/upload, secret read, and D: root scan flags false.
- Focused verification passed: `python -m py_compile tools\stage7_rewrite\scripts\build_atlas_social_identity_acceptance_gate.py`; `python -m pytest tools\stage7_rewrite\tests\test_build_atlas_social_identity_acceptance_gate.py -q` -> `2 passed`.

## Main source areas

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

## High-risk areas requiring operator approval before execution

- Archive capture and mptext archive batches.
- Asset download/retention batches.
- OCR poster batches.
- downstream LLM and Stage7 runner jobs.
- PCUI runtime import/verification against real artifact roots.
- Any D: drive large tree processing.
- Dajiala repair can spend API balance. Use canaries, chunking, and the budget guard before full runs.
- CloudRun deploy and mini-program upload remain final-stage actions. Run `npm run weekly:deploy-upload:preflight` first; it is read-only and includes the S25 DB2/DB3 relation guard, backend tests, and mini-program static tests.
- DJ Interview intake remains private-sidecar only. `npm run weekly:dj-interview:import` requires explicit internal-processing consent and redacts CLI/packet/workbench output; do not promote those records to DB/graph/public profile without a separate review packet.
- Mini-program mixtape/Instagram actions remain original-link only. `apps\weekly_activity_miniprogram\utils\externalLinkAction.js` rejects direct media file URLs before submit and copies platform page links; do not add audio/video cache, proxy, downloader, embed, or player behavior without rights-cleared hosting evidence.
- Mini-program WXML event wiring now has a static coverage guard. `page-event-handler-coverage.test.cjs` checks every `app.json` page for missing page methods behind static `bind*` / `catch*` handlers, while `share-wiring.test.cjs` derives page share coverage from `app.json` instead of a manual list. The deploy/upload preflight now dynamically includes every mini-program `*.test.cjs` file; S30 local preflight is report-only and passed `20` checks with the explicit-key Clean-CI gate skipped.

## Cleanup/readability findings

- The repository contains many dated top-level handoff files. They remain useful historical evidence, but current code-aligned truth is now centralized in `README.md`, `AGENTS.md`, and generated docs under `docs/`.
- Generated/runtime directories are numerous (`tmp-*`, `runs/`, `reports/`, `artifacts/`, `.mptext-data`, `.omc`). They should not be used as documentation authority.
- `src/cli.ts` is the operational command hub and should be kept in sync with `docs/CLI_REFERENCE.md` whenever command flags change.
- Archive success must be quality-gated. Browser captcha/platform HTML, Dajiala reconstructed HTML without meaningful article content, failed/partial archives, and stale empty `assets_local.json` are known failure modes.
- Short-link paid recovery must be product-gated. Run Dajiala `short2long` in account-balanced waves with per-account/failure fuses, then verify free archive/process outputs with `tools/auditShort2LongRecovery.mjs`; recovered/review may enter the LLM intake manifest with labels, while blocked rows must stay out of release.
- Recent-post backfill should not spend Dajiala while account-history prefetch and browser archive continue to work. Use `tools\stage7_rewrite\scripts\run-latest-free-archive-chunks.ps1`; merge recovered rows only, and send image-heavy review rows to OCR.
- The night watchdog is a control-plane script, not an extraction runner. It may restart recent free chunks/OCR under existing quality gates, write mailroom heartbeat, and run the latest-post Dajiala blocked canary with `-EnableDajialaCanary`; it must not start full93k, production vectors, or DB/graph batch writes. Historical empty-link Dajiala spending belongs to the separate `FULL_EMPTY_LINK_RECOVERY_20260507` wave lane.
- As of the 2026-05-07 18:55 CST snapshot, OCR, latest review OCR, latest free recovery, Stage7 canary, Stage7 batch50, Stage8 JSONL vector canary, and graph pack monitoring had completed. Historical full-empty paid-success recovery was processed through `PROCESS_WAVE_0013` and folded into `LLM_INTAKE_MANIFEST_20260507` as `5322 total / 4521 ready / 801 review / 0 blocked`. `SHORT2LONG_WAVE_0014` verified the remaining TAGChengdu tail as `0/20` success and `0` cost, so `WAVE_PLAN_0015` is held.
- Stage8 is implemented only to the JSONL canary boundary in this repo. It can build vector jobs and call Mac embedding endpoints for bounded JSONL output; production vector workers and Qdrant/Neo4j/PC DB batch writes remain explicitly blocked.
- Stage9 is implemented only as a graph candidate JSONL pack boundary. It is not a Neo4j writer and must not be treated as proof that production graph ingestion is ready.
- Weekly activity recommendation input is now a separate bounded lane. `build_weekly_activity_queue.py` can derive a since-cursor queue from a successful latest prefetch. The earlier `ret 200003 invalid session` blocker was resolved by the later session-refresh prefetch lane; keep that failure mode in mind, but do not treat it as the current blocker.
- 2026-05-07 18:55 CST audit found and fixed two runtime/test contract issues: OCR sidecar fallback was mislabeled as `command-or-sidecar` when `WECHAT_OCR_COMMAND` existed, and Rust sidecar fallback did not guarantee output at the caller-declared `outputPath`. Both are now covered by tests.
- Weekly activity mini-program output is now a static JSON interface over the evidence-gated main candidates. `build_weekly_activity_miniprogram_api.py` writes `current`, `by-city`, `by-date`, and `by-id` routes, and keeps review candidates out of the push-ready surface.
- The operator status snapshot must include side lanes. `show_93k_pipeline_status.py` now reports full-empty wave progress and weekly activity session status in addition to OCR/orchestrator state, reducing the chance that a heartbeat overlooks active paid/free recovery work.
- Bounded release candidates must not recursively scan the full D: artifact root unless a full release is explicitly intended. `finalize-llm-pack --intakeOnly --limit N` exists for canary packs and avoids the 2026-05-07 D: disk overload failure mode.
- PowerShell helper functions should avoid parameter names such as `$Args`; this caused Stage7 subcommand arguments to be dropped and canary runs to execute only `python -m stage7.cli`.
- Stage7 input audit should continue to discover article directories by `llm_input.md` rather than assuming a fixed two-level `account/token` layout, because multi-source release packs may use `source/account/token`.
- PCUI modules are split into many small files under `desktop/`; use `desktop/pcuiContract.js`, runtime guard modules, and tests before touching renderer behavior.
- Model/profile changes should update `docs/CONFIGURATION.md`, `profiles/*.json`, and prompt docs together.

## Code-change policy

This run changed archive quality gates, recapture tooling, OCR/vector support, and documentation. Before further code cleanup/refactor, create a scoped slice such as:

1. CLI command parser split.
2. PCUI module boundary cleanup.
3. Stage7 runner/profile cleanup.
4. archive/mptext runtime guard cleanup.
5. generated tmp/artifact ignore and retention policy cleanup.

Each slice should run `npm run build` and targeted tests.
# 2026-05-27 T5/T6 Sidecar Overlay Persistence Decision

- Added `tools\stage7_rewrite\scripts\build_atlas_t6_sidecar_overlay_persistence_decision.py` and focused regression `tools\stage7_rewrite\tests\test_build_atlas_t6_sidecar_overlay_persistence_decision.py`.
- Audit result: attach-only/read-model is the correct current persistence mode. Source/raw native social tables and selected serving native social tables are both `0`, while overlay joins to profile/search/graph/event are complete and relation coverage is `1,946/1,975`.
- Guardrails verified: duplicate candidate/selector/link-without-rollup/bad-kind rows `0/0/0/0`, leak hits `0/0/0`, selected serving and overlay opened read-only, all write/public/memory guards false.
- Validation: py_compile passed; focused pytest `3 passed`; combined overlay persistence/attach/overlay DB/completion pytest `14 passed`; strict URL/key/path grep over new report/output surface returned no hits.
