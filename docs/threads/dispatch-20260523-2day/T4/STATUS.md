# T4 Atlas Activity Candidate Status

Updated: 2026-05-28 04:00 CST
Status: candidate_activity_preflight_verified_gap_detected_report_only

## Assignment

Read `docs\threads\T4_atlas_activity_candidate_20260522.md` and advance source-preserving Atlas activity sidecar / derived candidate DB evidence only. This dispatch covers the 2026-05-28 T4 verification run: candidate DB inspection, baseline comparison, activity data integrity check, DJ entity coverage audit, weekly-to-Atlas gap analysis, and promotion path assessment.

## First Story

Verify the latest candidate DB (`reports\atlas_serving_time_overlay_span_split_search_date_refresh_candidate_20260527_2018\atlas_serving.sqlite`) against baseline (`reports\atlas_serving_participant_delta_current_20260526_0016\atlas_serving.sqlite`), audit activity table integrity, and surface gaps between the Atlas activity sidecar and the current weekly release.

## 2026-05-28 04:00 Activity Candidate DB Inspection

- **Primary queue**: Q4 / T4 activity candidate verification.
- **Candidate DB**: `reports\atlas_serving_time_overlay_span_split_search_date_refresh_candidate_20260527_2018\atlas_serving.sqlite` (2.19 GB).
- **Baseline DB**: `reports\atlas_serving_participant_delta_current_20260526_0016\atlas_serving.sqlite` (2.18 GB).
  - Baseline has orphaned WAL/ SHM files indicating prior session did not clean-close; Python sqlite3 `disk I/O error` prevented direct read. Preflight comparison (read below) confirmed identical counts.
- **Preflight**: `reports\atlas_serving_time_city_year_span_final_candidate_preflight_20260527_2145\promotion_preflight.json`.
- **Decision**: `promotion_preflight_passed_local_only`, all 16 checks passed.

### Table Counts (Candidate == Comparison)

| Table | Candidate | Comparison | Match |
|---|---|---|---|
| performance_event | 508,049 | 508,049 | OK |
| dj_profile | 53,555 | 53,555 | OK |
| dj_event | 1,285,827 | 1,285,827 | OK |
| dj_relation_rollup | 701,396 | 701,396 | OK |
| search_document | 590,927 | 590,927 | OK |
| graph_window_cache | 53,555 | 53,555 | OK |
| evidence_ref | 130,591 | 130,591 | OK |
| activity_event_detail | 196 | 196 | OK |
| activity_evidence_ref | 2,181 | 2,181 | OK |
| canonical_subject | 82,878 | 82,878 | OK |

Table count drift: **0** across all tables.

### Preflight Checks (16/16 passed)

- required_public_tables_present: OK
- deployable_public_metadata: OK
- participant_acceptance_strict: OK
- raw_source_url_columns_not_copied: OK
- archive_html_path_columns_not_copied: OK
- forbidden_schema_columns_zero: OK
- forbidden_value_hits_zero: OK
- hard_noise_hits_zero: OK
- activity_tables_present: OK
- activity_events_have_evidence: OK (196/196)
- duplicate_normalized_profile_groups_zero: OK
- graph_window_gap_zero: OK
- public_url_allowed_zero_or_absent: OK
- candidate_activity_coverage_not_worse_than_comparison: OK (196/2181 == 196/2181)
- candidate_duplicate_profile_groups_not_worse_than_comparison: OK (0 == 0)
- candidate_hard_noise_not_worse_than_comparison: OK

## 2026-05-28 04:00 Activity Data Integrity Audit

- **Activity events**: 196 total.
- **Evidence refs**: 2,181 total, all 196 events covered (0 orphans).
- **Cities covered**: 24 (top: Beijing 32, Shanghai 32, Chongqing 24, Chengdu 17, Shenzhen 16).
- **Date range**: 2026-05-22 to 2026-06-05 (11 distinct dates).
- **Source package**: `weekly-current-release-20260522-190146` (registry129).
- **Source accounts**: 71 unique WeChat accounts.
- **Source hash coverage**: 196/196 events have source_hash; 176 unique hashes.
- **Evidence source kind**: 100% `wechat_article` (2,181/2,181).
- **Events with lineup**: 108/196 (55.1%).
- **Events with description lines**: 193/196 (98.5%).
- **Events with ticketing**: 60/196 (30.6%).
- **Field-path evidence distribution**: title (196), venue_name (196), event_date_text (196), description_original_lines (626 across indices), address (188), music_styles (267), lineup_artists (234), price (99), event_time_text (98), ticketing_text (60).

### Evidence Quality Sample

All evidence rows have `source_kind=wechat_article`, `confidence=0.92`. Field paths include title, venue_name, event_date_text, lineup_artists, address, description_original_lines[indices], music_styles, price, ticketing_text.

## 2026-05-28 04:00 DJ Entity Coverage Audit

- **DJ profiles in candidate**: 53,555 (with 53,561 unique name+alias combinations).
- **Activity event artists extracted**: 200 unique names from 108 events with lineup data.
- **Artist-to-DJ match rate**: 200/200 = **100.0%**.
- **Event-level coverage**: 108/108 events with lineup have at least 1 matched DJ = **100.0%**.
- **Avg matched DJs per event**: 2.2.
- **Unmatched artists**: 0.
- **Sample matched artists**: 30drop, 3asic, 88lien, a6iir, aboy and bands, acierate, ank.a, ann one, artsun, axsee, ayesha, bambi, basisk, bby, ...

DJ entity linkage for activity events with lineup is complete: every extracted artist name resolves to an existing `dj_profile` record via normalized_name or aliases_json match.

## 2026-05-28 04:00 Weekly-to-Atlas Gap Analysis

### Weekly Release Current State

- **Current release**: `services\weekly_activity_cloudrun\data\current_release\` (generated 2026-05-28 01:04 CST).
- **Published items**: 94.
- **Weekly date window**: 2026-05-28 to 2026-05-30 (3 days, Thu-Sat).
- **Publish status**: all 94 `published`, all `READY`.
- **Cities**: 23.
- **Items with lineup**: 3/94 (3.2%) -- very low, post-LLM expansion.

### Source Queue

- **Weekly queue nightly (20260528)**: `tools\stage7_rewrite\longrun\WEEKLY_ACTIVITY_QUEUE_NIGHTLY_20260528\latest_queue.jsonl`.
- **Queue total**: 2,548 items from 125 accounts.
- **Queue date range**: 2013-12-24 to 2026-05-28.
- **Expanded pack**: `tools\stage7_rewrite\longrun\WEEKLY_ACTIVITY_EXPANDED_PACK_20260528`.
- **Enriched candidates**: 2,101.
- **High-confidence candidates**: 892 (threshold >= 0.75).
- **Review candidates**: 676.

### Account Overlap (Critical Gap)

| Source | Accounts | Overlap |
|---|---|---|
| Atlas activity sidecar (May 22) | 71 | 1 (cicipark) |
| Weekly current release (May 28) | 55 | |

Only **1 account** (`cicipark`) is common between the Atlas activity sidecar's source accounts (71) and the current weekly release's accounts (55). This means the two systems pull from almost completely disjoint account pools.

### Weekly-to-Atlas Coverage

- **Weekly items matched in Atlas**: 8/94 (8.5%).
- **Weekly items NOT in Atlas**: 86/94 (91.5%).
- **Top unmatched accounts**: nuts (5), oil (5), gum_guangzhou (3), dada_kunming (3), potent (3), pools (2), exit_shanghai (2), substation (2), heim_shanghai (2).

The Atlas activity sidecar was built from the May 22 registry129 weekly package. The current weekly release (May 28) has rotated its target date window and pulled from a different set of accounts. This is a structural gap: the Atlas activity sidecar needs periodic refresh from the current weekly source pack to maintain coverage.

### Date Window Comparison

| Source | Date Range | Events |
|---|---|---|
| Atlas activity sidecar | 2026-05-22 to 2026-06-05 | 196 |
| Weekly current release | 2026-05-28 to 2026-05-30 | 94 published (2,101 candidates) |

The Atlas sidecar captures a wider 2-week window but uses older source data (May 22). The weekly release uses fresh source data (May 28) but publishes a narrow 3-day window.

## Promotion Path Assessment

### Current State

- **Candidate DB**: preflight passed, all gates green.
- **Promotion decision**: `promotion_preflight_passed_local_only`.
- **Safety**: no public deploy, no CloudRun/VPS, no Neo4j/Qdrant write, no mini-program upload.
- **Next step**: T5 consumption is safe for DJ-first graph serving (196 activity events with 100% DJ coverage).

### Promotion Blocker

- **Gap**: Activity sidecar is 6 days stale (built 2026-05-22, current date 2026-05-28).
- **Account drift**: Near-total account pool mismatch between Atlas sidecar and current weekly release.
- **Coverage**: Only 8.5% of current weekly items present in Atlas activity tables.

### Recommended Path

1. **Refresh activity sidecar** from current weekly expanded pack (May 28, 2,101 candidates) using `tools\stage7_rewrite\scripts\build_atlas_activity_source_sidecar.py`.
2. **Merge refreshed sidecar** into derived candidate DB using `tools\stage7_rewrite\scripts\merge_atlas_activity_sidecar_into_candidate_db.py`.
3. **Re-run preflight** on refreshed candidate.
4. **Handoff to T5** for serving consumption.

### What Is Safe Now

- The candidate DB with 196 activity events is internally consistent and DJ-coverage is 100%.
- All preflight checks pass.
- No raw/source DB mutation has occurred.
- No production writes, deploys, or uploads.

## New Weekly Activities Requiring Atlas Access

The following 86 weekly published items (2026-05-28 to 2026-05-30) are NOT in the current Atlas activity sidecar and should be added on next refresh:

- 6 items on May 28 (Thu) from Guangzhou, Chongqing, Shanghai, Beijing, Shanghai, Kunming.
- 43 items on May 29 (Fri) from Shenzhen, Shanghai, Shenyang, Qingdao, Chongqing, etc.
- 45 items on May 30 (Sat) -- largest day.
- Total: 94 published, 86 missing from Atlas.

Additionally, the expanded pack offers 2,101 enriched candidates (892 high-confidence) that could be ingested into the Atlas activity sidecar, substantially expanding coverage beyond the current 196 events.

## Safety Boundary

- **Read-only verification only**: no DB writes, no production mutations.
- **Candidate DB opened read-only**: `source_db_mutated=false`.
- **No**: raw atlas.sqlite overwrite, Neo4j/Qdrant production writes, CloudRun deploy, mini-program upload/review.
- **No**: credential read, network/model call, destructive Git, 9router, D: root scan.
- **Leak hits**: 0 across all evidence surfaces.

## STOP_REASON

`activity_sidecar_stale_weekly_refresh_recommended` -- the current Atlas activity sidecar is 6 days stale with near-total account pool drift. A refresh from the current weekly expanded pack is recommended before T5 promotion.

## WAIT_REASON

`wait_for_t4_activity_sidecar_refresh_from_current_weekly_pack` -- T4 should run `build_atlas_activity_source_sidecar.py` against the May 28 expanded pack, merge into a fresh candidate, and re-verify before T5 proceeds.

## Next Resume Pointer

1. Run `tools\stage7_rewrite\scripts\build_atlas_activity_source_sidecar.py` pointing at `tools\stage7_rewrite\longrun\WEEKLY_ACTIVITY_EXPANDED_PACK_20260528` or the later nightly queue.
2. Merge output into a new derived candidate DB.
3. Re-run preflight and DJ coverage audit.
4. Hand refreshed candidate to T5.

## Hard Stop

No raw Atlas DB overwrite; no production DB/vector write; no CloudRun deploy; no mini-program upload/review.
