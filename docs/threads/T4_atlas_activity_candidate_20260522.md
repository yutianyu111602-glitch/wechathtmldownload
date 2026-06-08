# T4 Atlas Activity Candidate Thread

Status: `CURRENT_AUTHORITY`
Updated: 2026-05-26 17:02 CST
Thread owner: source-preserving Atlas Route B, activity sidecar, candidate DB merge, loss-chain audit.

## Purpose

Own the lossless daily Atlas route from weekly/current source facts into additive Atlas candidate artifacts. This thread corrects the stale shorthand that old generic Stage7 LLM output is enough for Atlas daily refresh.

## Current State

- 2026-05-26 source/raw mapping probe for manual participant write gates:
  - upstream Q6 report `reports\ATLAS_T6_MANUAL_PARTICIPANT_SOURCE_RAW_MAPPING_PROBE_20260526.md`
  - summary `tools\stage7_rewrite\reports\atlas_social_manual_participant_source_raw_mapping_probe_q6_20260526\source_raw_mapping_probe_summary.json`
  - decision `atlas_social_manual_participant_source_raw_mapping_probe_ready_report_only`; failed checks `[]`
  - input target rows `8`; lane split source-date / overnight-midnight / remaining-identity `3/1/4`; direct existing explicit source/raw target DB paths `1`; mapping ready/blocked rows `8/0`
  - T4 interpretation: the generic 46-row current activity-candidate probe remains blocker evidence, but these `8` mapped rows now have report-only target provenance ready for a T5 read-only real snapshot gate
  - no source/raw DB write, derived candidate mutation, serving rebuild/write, graph/vector/public/deploy/upload/memory action occurred
- Current full pipeline understanding report: `reports\PIPELINE_FULL_UNDERSTANDING_AND_LOSS_CHAIN_20260522.md`.
- Loss-chain decision for the old route: `not_lossless_old_stage7_path`.
- 2026-05-25 current sidecar additive derived-candidate refresh:
  - report `reports\ATLAS_T4_ACTIVITY_CANDIDATE_CURRENT_REFRESH_20260525.md`
  - output DB `reports\atlas_incremental_wechat_refresh_20260522_1438\atlas_local_sqlite_db_139123_activity_candidate_current_20260525_1435\atlas.sqlite`
  - merge summary `reports\atlas_incremental_wechat_refresh_20260522_1438\atlas_local_sqlite_db_139123_activity_candidate_current_20260525_1435\activity_candidate_db_merge_summary.json`
  - alignment summary `tools\stage7_rewrite\reports\atlas_activity_sidecar_current_alignment_t4_20260525\atlas_activity_sidecar_current_drift_summary.json`
  - decision `atlas_activity_sidecar_current_aligned_report_only`; sidecar and candidate activity events/evidence `196/2,181`; event drift `0/0`; core event field changes `0`; evidence natural-key drift `0/0`
  - safety: base DB copied into a derived candidate path, `source_db_mutated=false`, raw URL leak hits `0`
  - consumed by T5 in `reports\ATLAS_T5_ACTIVITY_CURRENT_SERVING_PRODUCTION_CANDIDATE_20260525.md`; no raw Atlas DB overwrite, serving/public pointer, Neo4j/Qdrant, CloudRun/VPS, mini-program upload/review, memory, credential, destructive Git, 9router, or D: root action occurred
- 2026-05-25 current sidecar drift audit:
  - report `reports\ATLAS_T4_ACTIVITY_SIDECAR_CURRENT_DRIFT_AUDIT_20260525.md`
  - script `tools\stage7_rewrite\scripts\audit_atlas_activity_sidecar_current_drift.py`
  - summary `tools\stage7_rewrite\reports\atlas_activity_sidecar_current_drift_t4_20260525\atlas_activity_sidecar_current_drift_summary.json`
  - decision `atlas_activity_sidecar_current_drift_refresh_needed_report_only`
  - current sidecar `reports\atlas_activity_source_sidecar_current_20260523_132244\atlas_activity_source_sidecar.sqlite` has `196/2,181` events/evidence, while the derived candidate and selected serving activity tables have `196/2,171`
  - event IDs are aligned, but core event field changes `17`; current sidecar evidence rows missing from candidate by natural key `19`; candidate-only stale evidence rows `9`
  - no raw/source Atlas DB overwrite, derived candidate/serving DB mutation, Neo4j/Qdrant write, CloudRun deploy, mini-program upload/review, memory write, credential read, network/model call, destructive Git, or D: root scan occurred
  - next safe T4 slice is an additive derived-candidate refresh from the current sidecar, not a raw Atlas DB mutation
- Activity sidecar built from registry129 weekly package:
  - `reports\atlas_activity_source_sidecar_registry129_20260522_1901`
  - activity events `196`
  - EvidenceRef rows `2171`
  - PROV-lite rows `1`
  - source URL hash coverage `196/196`
  - raw URL leak hits `0`
- Derived candidate DB:
  - `reports\atlas_incremental_wechat_refresh_20260522_1438\atlas_local_sqlite_db_139123_activity_candidate\atlas.sqlite`
  - base counts `articles=139123`, `entities=1515202`, `events=609235`
  - added `atlas_activity_events=196`, `atlas_activity_evidence_refs=2171`, `atlas_activity_prov_activities=1`

## Owns

- Atlas incremental host HTML/source artifact generation.
- OCR and LLM input evidence quality audit for incremental Atlas refresh.
- Activity-aware source sidecar from weekly/current packages.
- Additive merge of `atlas_activity_*` tables into derived candidate DB.
- Loss-chain audit and promotion blocker report.

## Does Not Own

- Weekly backend publish decision.
- DJ-first serving model promotion.
- Raw Atlas source SQLite mutation.
- Neo4j/Qdrant production writes.
- Mini-program frontend upload/review.

## Source Documents

- `reports\PIPELINE_FULL_UNDERSTANDING_AND_LOSS_CHAIN_20260522.md`
- `docs\WEEKLY_MINIPROGRAM_ATLAS_EVIDENCE_PROVENANCE_V2_PLAN_20260521.md`
- `docs\current-runtime.md`
- `reports\atlas_incremental_wechat_refresh_20260522_1438\ATLAS_INCREMENTAL_LOSS_CHAIN_AUDIT_20260522.md`
- `reports\atlas_activity_source_sidecar_registry129_20260522_1901\summary.md`
- `reports\atlas_incremental_wechat_refresh_20260522_1438\atlas_local_sqlite_db_139123_activity_candidate\activity_candidate_db_merge_summary.md`

## Key Scripts

- `tools\stage7_rewrite\scripts\build_atlas_incremental_host_html_artifacts.py`
- `tools\stage7_rewrite\scripts\audit_atlas_incremental_loss_chain.py`
- `tools\stage7_rewrite\scripts\build_atlas_activity_source_sidecar.py`
- `tools\stage7_rewrite\scripts\merge_atlas_activity_sidecar_into_candidate_db.py`
- `tools\stage7_rewrite\scripts\stage7_deepseek_flash_pilot.py` as secondary projection evidence only.
- `tools\stage7_rewrite\scripts\materialize_flash_stable_extracts.py` as secondary projection evidence only.

## Output Contract

A T4 run should leave:

- source artifact run directory;
- loss-chain audit JSON/Markdown;
- activity sidecar SQLite/JSONL/summary;
- derived candidate DB path;
- leak scan result;
- explicit handoff to T5 when a serving candidate should consume `atlas_activity_*` tables.

## Gates

- Old generic Stage7 path must not be called lossless unless activity sidecar and candidate merge compensate for rich-field loss.
- Candidate merge must be additive into a derived DB, not raw Atlas DB.
- Raw source URLs, local paths, raw HTML, and raw JSON must not leak into public docs or public serving outputs.

## Next Bounded Tasks

1. Teach the public-safe serving read model/API layer to read `atlas_activity_*` tables where useful.
2. Make promotion readiness fail when old Stage7 loss-chain evidence lacks an activity-aware compensating sidecar.
3. Add OCRSpan support only when the current API package exposes per-image OCR spans.

## Thread Prompt

```text
你是 T4 Atlas Activity Candidate 线程。只负责 weekly/current source facts 到 Atlas activity sidecar 和 derived candidate DB 的无损桥。
先读 docs/threads/THREADS_INDEX_20260522.md、reports/PIPELINE_FULL_UNDERSTANDING_AND_LOSS_CHAIN_20260522.md、docs/WEEKLY_MINIPROGRAM_ATLAS_EVIDENCE_PROVENANCE_V2_PLAN_20260521.md。
输出 sidecar、candidate DB、loss-chain audit、leak scan，并说明 raw Atlas DB 是否未改。
禁止：raw atlas.sqlite overwrite、Neo4j/Qdrant production 写入、CloudRun deploy、小程序上传/提审、把旧 generic Stage7 宣称为无损日更。
```
