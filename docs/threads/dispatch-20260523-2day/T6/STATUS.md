# T6 DeepSeekTUI / LDR Sidecar Status

Updated: 2026-05-28 02:00 CST
Status: year_context_review_blocked_avatar_provenance_blocked_social_overlay_consumed

## Assignment

Read `docs/threads/T6_deepseektui_ldr_sidecar_20260522.md` and supervise DeepSeekTUI/LDR outlink/avatar/profile crawling for T4/T5 gaps. Output is candidate evidence until T5/T7 verify it.

## First Story

Prepare or run bounded candidate research packets, verify provider/status docs without reading or printing secrets, and log budget/evidence when external APIs are used.

---

## Comprehensive T6 State Assessment (2026-05-28)

### 1. Year-Context Review (BLOCKED)

- Report: `reports/ATLAS_T6_TIME_TITLE_YEAR_CONTEXT_REVIEW_20260527.md`
- Summary: `tools/stage7_rewrite/reports/atlas_t6_time_title_year_context_review_20260527/year_context_review_summary.json`
- **Result**: 1,366 rows reviewed, **0 ready**, 1,366 blocked
- Blocked breakdown:
  - source_artifact_required_for_year_context: **443** (need actual source artifact to determine year)
  - weekday_year_candidate_review_required: **647** (weekday patterns with ambiguous year)
  - conflict_or_ambiguous: **276** (conflicting year candidates)
  - multi_event_guide_or_news: **41** (guide/news articles with multiple events, no single date)
  - month_day_candidate_missing_or_multiple: **231**
  - multi_year_context_review_required: **3**
  - first_source_time_multiple_explicit_dates: **1**
- LLM audit: No deterministic ready rows were safe. A single year plus multiple month/day candidates must stay blocked.
- **Next resume pointer**: `tools/stage7_rewrite/reports/atlas_t6_time_title_year_context_review_20260527/year_context_source_artifact_required_rows.jsonl`
- This queue needs actual source HTML/article artifacts or human date-context review before any T5 write gate.

### 2. Time-Title Recovery: Consumed Evidence

#### Span/Split Recovery (Complete)
- T6 review: 16 input, 14 ready, 2 blocked (multi-event guide/news)
- T6 readback: 14/14 ready
- T5 consumed: 51 source/raw `events.time_iso` rows committed, 395 serving `starts_at` changes (47 perf_event + 348 dj_event)
- Remaining blocked: 2 multi-event guide/news rows (OIL Club multi-date events that cannot collapse into a single date)

#### Year/Span Recovery (Complete)
- T6 input: 1,281 month/day-year + 168 span/range = 1,449
- T6 ready: 64 rows (55 year-month-day + 9 span-start)
- T6 readback: 64/64 ready; covers 448 perf_event + 2,703 dj_event missing starts_at
- T5 consumed: 242 source/raw `events.time_iso` rows committed, 2,703 serving `starts_at` changes (380 perf_event + 2,323 dj_event)
- Gap improvement: perf_event starts_at 154,410->154,030 | dj_event starts_at 432,247->429,924
- Blocked: 1,385 rows remain in blocked queues (weekday mismatch, year context, conflict)

#### Exact-Date Recovery (Complete)
- From 2,000 time-title work orders: 78 candidate-ready rows
  - 75 exact full-date | 2 relative-post-date | 1 month-day-with-post-date
- Deferred queues:
  - month_day_year_required: 1,281
  - span_or_range_review: 168
  - relative_date_source_context: 352
  - ambiguous_multiple_date: 13
  - weak_false_date_token: 4
  - source/OCR/manual recovery: 104
- T5 consumed 75/78 rows into 690 source/raw `events.time_iso` writes + 3,333 serving changes
- 3 groups remain blocked (source/raw exact title/venue/date mapping missing)

### 3. Avatar / Media Recovery

#### v4 Manifest (Complete)
- 68 avatar artifacts from v4 redacted manifest (supersedes old validation with only 2)
- Hash-addressable: 68/68 | DJ-first: 25 | non-DJ: 41 (venue=31, label=10) | missing rollup: 2
- Platform split: youtube 47, instagram 19, soundcloud 2
- Media signal rollups: 74 total, 25 DJ-first
- Old validation gap: old manifest only had 2 avatars (both blocked, 0 hash-ready)

#### Storage Contract Gate (Ready)
- 68/68 storage-contract ready, 0 blocked
- DJ-first: 25 | non-DJ: 43
- Entity-kind split: dj=25, venue=31, label=10, missing_rollup=2

#### Entity Binding Gate (Partial-Ready)
- 25 DJ-first input, 24 bound to Atlas `dj_id`, 1 blocked
- Serving search/graph readback: 24/24
- Unique bound serving DJ IDs: 23
- Duplicate serving-DJ avatar groups: 1
- Primary avatar selection review: 2 rows pending
- Binding blocked: 1 (DJ HEARTSTRING -- name/alias mismatch with selected serving)

#### Binary Storage Provenance Gate (BLOCKED)
- **23 rows blocked** -- decision `atlas_t6_avatar_binary_storage_provenance_gate_blocked_report_only`
- Failed checks:
  - `binding_repair_rows_present` (1 -- DJ HEARTSTRING)
  - `binary_source_provenance_missing` (23 -- no explicit binary source root)
  - `storage_target_provenance_missing` (23 -- no explicit storage target root)
- Primary avatar candidates: 23 | superseded: 1 | unresolved: 0
- Binary files scanned: 0 | hash rows: 0
- **Next**: Explicit bounded binary source root and storage target root, plus DJ HEARTSTRING repair

### 4. Social / Profile Sidecar (Consumed by T5)

#### WSL2 Scratch Source
- dj_social_profiles: 24,184 | dj_outlinks: 8,300 | dj_identity_candidates: 184 | dj_avatars: 2
- WSL supervisor: COMPLETE_POST_FILTER_DONE/COMPLETE, processed 246,024/246,024/0

#### Redacted Manifest (Complete)
- 18,741 joined candidates | 1,986 entity rollups | 2 avatar artifacts | 12,260 blocked rows
- Raw URLs and local paths removed; non-numeric confidence labels mapped to 0.0

#### Validation Gate (Complete)
- Merge-precheck-ready: 18,710 profile/outlink rows
- Identity review-required: 31 (need stronger source-context evidence)
- Avatar hash-ready/blocked: 0/2
- Duplicate candidate/url-key groups: 0/0
- Missing serving entity refs: 0

#### Overlay DB (Built)
- Report-local overlay SQLite: 10 MB, 18,710 social link rows, 1,975 DJ entities
- 15,715 profile rows + 2,995 outlink rows
- 122 distinct platforms, 1,961 hosts
- SHA256: f9a89d86...

#### UI/API Integration (Complete)
- Social read-model candidate: 1,975 detail/search/graph rows, route smoke ok=true
- Consumer smoke: 5 route contracts (overview/detail/search/platform/graph)
- UI integration review: Cytoscape elements 136 (34 nodes + 102 edges)
- Rendered UI smoke: 12 workbench samples, 0 blank, 5 route panels, preview graph 75 elements
- All 1,975 entities attach-ready, 0 blocked

### 5. Manual Participant Research (Q6)

- **Source-date acceptance write gate**: 3 rows ready but blocked on source/raw target DB provenance missing
- **Overnight-midnight**: 1 row readback-ready, blocked on source/raw target DB provenance
- **Remaining-identity**: 4 readback-ready rows (2 date-resolved + 2 venue-alias), blocked on source/raw target DB provenance
- **Mapped source/raw gates**: 8 rows mapped to explicit source/raw target, provenance ready 8/0, but write execution allowed 0
- **Blocked identity review**: Cod.Act blocked (no Atlas source context found)
- **YYYY**: Accepted as source-context-ready, staging-only HAS_PROFILE edge written and verified

### 6. DeepSeekTUI / SearXNG Provider State

- SearXNG: serpapi google (default), brave api (disabled from default pool, explicit fallback)
- DuckDuckGo, Startpage, Google HTML, Brave HTML: quarantined (timeout/CAPTCHA/429)
- DeepSeek models: deepseek-v4-pro and deepseek-v4-flash verified available
- LDR: routes through OpenAI-compatible DeepSeek endpoint
- Provider check: not re-probed; use lightweight current status check before any real sidecar run

### 7. T6 Output Contract Summary

| Output | Status | Rows | Blocked |
|--------|--------|------|---------|
| Redacted manifest | Complete | 18,741 candidates | 12,260 |
| Social overlay DB | Complete | 18,710 links | 0 |
| Avatar media recovery | Ready | 68 artifacts | 23 (provenance) |
| Exact-date recovery | Complete | 78 ready (2000 input) | 1922 deferred |
| Year/span recovery | Complete | 64 ready (1449 input) | 1385 deferred |
| Span/split recovery | Complete | 14 ready (16 input) | 2 |
| Year-context review | BLOCKED | 0 ready (1366 input) | 1366 |
| Bounded profile fetch | Complete | 12/12 SoundCloud | 0 |

### 8. Remaining T6 Work Queues (Priority Order)

| Priority | Lane | Queue | Status |
|----------|------|-------|--------|
| 0 | Year-context source artifacts | `year_context_source_artifact_required_rows.jsonl` (443 rows) | BLOCKED -- needs actual source HTML |
| 1 | Year-context weekday review | `year_context_weekday_review_required_rows.jsonl` (647 rows) | PENDING |
| 2 | Avatar binary source root | `avatar_binary_storage_blocked_rows.jsonl` (23 rows) | BLOCKED -- needs explicit binary source path |
| 3 | Relative-date source context | `relative_date_source_context_required_rows.jsonl` (352 rows) | PENDING |
| 4 | Identity review recovery | 31 identity candidates | PENDING -- needs stronger source-context |
| 5 | Source/OCR gap recovery | `source_ocr_gap_recovery_work_orders.jsonl` (2000 rows) | PENDING |

### 9. Key Blocker Descriptions

1. **Year-context queue (1,366 rows)**: Single year with ambiguous month/day evidence cannot produce deterministic dates. 443 need actual source article HTML. 647 need human/weekday review. 276 have conflicting evidence. 41 are multi-event guide/news articles.

2. **Avatar binary provenance (23 rows)**: 23 avatar candidates have DJ-first entity bindings and storage contracts ready, but no explicit binary source root (where the binary files live) and no explicit storage target root (where to put them). One additional repair (DJ HEARTSTRING) needed.

3. **Source/OCR acquisition**: Latest bounded fetch got 5/5 HTTP 200 responses from WeChat URLs, but all 5 were verification shells (js_content_text_len=0), yielding 0 article artifacts. No OCR generation or acceptance possible from verification shells.

4. **Identity review (31 candidates)**: 31 social profile candidates need additional source-context evidence before they can be promoted to accepted identity status.

### 10. Next Resume Pointers

| Priority | Lane | Resume Pointer |
|----------|------|---------------|
| 0 | Year-context review | `tools/stage7_rewrite/reports/atlas_t6_time_title_year_context_review_20260527/year_context_source_artifact_required_rows.jsonl` |
| 1 | Avatar binary provenance | `tools/stage7_rewrite/reports/atlas_t6_avatar_binary_storage_provenance_gate_20260527/avatar_binary_storage_blocked_rows.jsonl` |
| 2 | Relative-date source context | `tools/stage7_rewrite/reports/atlas_t6_time_title_exact_date_recovery_20260527/relative_date_source_context_required_rows.jsonl` |
| 3 | Source/OCR recovery | `tools/stage7_rewrite/reports/atlas_t5_time_city_venue_gap_closure_20260527/source_ocr_gap_recovery_work_orders.jsonl` |
| 4 | Swarm T6 dispatcher | `tools/stage7_rewrite/scripts/atlas_swarm_t6_year_context_dispatcher.py` (for year-context dispatch) |

### Safety

- leak_counts: public_url/sensitive_key/local_path 0/0/0 across all T6 reports
- Boundary: T6 never runs crawler/OCR/model/network action without explicit authorization. All source/raw DB, serving SQLite, graph/vector/public state, huaidj.club upload, CloudRun/VPS deploy, mini-program, memory, credential, 9router, and D-root scans remain unchanged.
- Provider keys: never read or printed
