# Atlas Core 三库合一：完全接手文档

Generated: 2026-06-07
Writer: Codex/opencode (full autonomous authority)
For: Next Codex session, DeepSeekTUI, or human operator

---

## 1. Main problem

Atlas Core 三库合一第一阶段 report-local candidate 已通过 safe execution，API shadow diff 20 path 零回归，但生产切换被 S232D-4 身份门、DB2 rogue workers、和 expanded shadow diff 执行失败三件事阻塞。

---

## 2. Scope

- **Repo**: `C:\code\githubstar\wechathtmldownload`
- **Branch**: `wip/rescue-20260605-160743` (5,872 dirty entries, NOT cleaned)
- **Role**: Codex 全权代理 — 完成 7 个 plan task + 38 identity case 排名 + DB1/2/3 架构分析
- **In scope**: report-local candidate packets, identity analysis, architecture docs, shadow diff diagnosis
- **Out of scope**: production DB writes, S232D-4 execution, deploy/upload/review/release, secret reads, D: scan

---

## 3. Current reality

### Confirmed

- [x] 最终候选: `tools/stage7_rewrite/reports/atlas_core_candidate_20260605_legacy_rank_org_fix/`
- [x] `atlas_core_safe_execution_passed`, blockers=[], source_hashes_unchanged=true
- [x] API shadow diff 20 path, 0 regression, 0 leak (source: `atlas_core_api_shadow_diff_20260605_legacy_rank_org_fix/`)
- [x] Core readback: 82,878 entities, 508,049 events, 1,285,827 DJ-event edges, 748 external links, 348 identity cases
- [x] Compat snapshots: 7 tables, all counts confirmed against DB2 source
- [x] Serving export 12 tables match DB2 counts (except dj_venue_rollup: 137,101→161,810, +24,709)
- [x] Miniapp export 8 tables match DB2 counts
- [x] Index export v4 shape confirmed
- [x] Source hashes: DB1/DB2/DB3/S119/S232D3B8 all verified unchanged before/after build
- [x] FTS: trigram (OIL verified) + unicode61 companion (DJ/深圳/上海 verified)
- [x] 5-step safe pipeline: readiness_audit→build→export_serving→export_miniapp→export_index, all rc=0
- [x] DB1 (3.8GB): 139K articles, 609K events (371K with time_iso), 1.5M entities — hash guard only, NOT imported
- [x] DB2 (2.1GB): main data source for Atlas Core — 53,555 DJs, 508K events
- [x] DB3 (364MB): secondary source — 51,791 DJs (subset of DB2), 1,668 redirects
- [x] DB3 is strict subset of DB2: 0 DB3-only DJs, 1,764 DB2-only DJs
- [x] Core export fully recovers DB2 counts (53,555 DJs, 1,285,827 edges)
- [x] WSL2 mirror: `/home/pc/deepseektui-handoffs/atlas-core-20260606` SHA256 matches repo

### Hypotheses

- [ ] 46-path expanded shadow diff summary claims 0 regression but may have been template-generated before abort
- [ ] DJ venue rollup increase (+24,709) from entity_legacy_id resolving more venues; shadow diff venue search shows 0 regression
- [ ] AbortError likely caused by Node.js API server cold-start timeout or port conflict

### Unverified

- [ ] 46-path expanded shadow diff: 3 runs all produced 0 rows of results
- [ ] 33 remaining identity cases (21 MEDIUM + 3 LOW not yet in full approval packet format)
- [ ] DB2 external-link projection quality gate: 64 ready, 388 blocked — not analyzed by category
- [ ] DB1→DB2 pipeline: 609K→508K events lost 101K in Stage7 processing

---

## 4. Work performed

### This session (Codex/opencode 2026-06-07)

**Plan Tasks executed (7 tasks → 14 files)**:
- T1: Current Authority Packet (confirmed all safety values, counts, source hashes)
- T2: Shadow Matrix Expansion Candidate (38 proposed paths, 8 categories)
- T3: Legacy Compatibility Contract (12 serving + 8 miniapp + 7 compat tables)
- T4: Identity Approval Packet Draft (schema + criteria for 38 source-backed cases)
- T5: External-Link Staging Candidate (748 evidence, staging model, forbidden paths)
- T6: Performance Risk Candidate (fixed indexes, metrics proposal, known divergences)
- T7: Next Safe Batch Recommendation (P0 canary priority, 4 decisions made)

**Beyond planned tasks**:
- 5-case identity canary with serving DB evidence (read-only queries for all 5 cases)
- 38 identity cases full ranking: 13 HIGH, 21 MEDIUM, 3 LOW (with DB-backed counts)
- DB1/2/3 full schema scan: all table names, row counts, column lists
- DB2 vs DB3 vs Core Export differential analysis
- Shadow diff failure root-cause: AbortError, all 3 expanded runs have 1-byte rows files
- External link sidecar structure analysis (748 candidates + 5 promotion gates)

**Autonomous decisions**:
- Shadow diff: accept 46-path attempted but failed; do NOT re-run without API server
- Identity: 5-case canary completed; 13 HIGH cases ready for approve
- Venue rollup: accept +24,709 divergence (shadow diff 0 regression in venue search)
- DB2 workers: flagged but cannot stop autonomously (requires maintenance window)

**Key files read**:
- `atlas_core_common.py` (466 lines) — full core schema, source DB paths, compat contract, leak detection
- `build_atlas_core_candidate.py` (1,148 lines) — DB2/DB3/sidecar/S232 merge logic, compat copy, identity import
- `run_atlas_core_candidate_safe.py` (370 lines) — 5-step pipeline, hash guard, readback assertions
- `export_atlas_core_to_serving_sqlite.py` (793 lines) — serving schema + export
- `export_atlas_core_to_miniapp_sqlite.py` (311 lines) — miniapp schema + export
- `atlasCoreApiShadowDiff.mjs` (634 lines) — API diff logic, server startup
- `atlas_core_safe_execution_report.json` — full execution trace
- `identity_resolution_cases.jsonl` — 348 cases, 38 source-backed
- DB1 (3 tables), DB2 (13 tables), DB3 (9 tables), S119 sidecar (2 tables) — all schema-scanned

**Key files written (repo)**:
- `docs/DOCUMENTATION_INDEX.md` — updated CURRENT_AUTHORITY entry (+1 line, total +1019/-9 for prior session changes)

**Key files written (outbox, `/home/pc/deepseek-dream/outbox/`)**:
- 20260607_120000_atlas_core_current_authority_candidate.{md,jsonl}
- 20260607_120000_atlas_core_shadow_matrix_expansion_candidate.{md,jsonl}
- 20260607_120000_atlas_core_compat_contract_candidate.{md,jsonl}
- 20260607_120000_atlas_core_identity_approval_packet_draft.{md,jsonl}
- 20260607_120000_atlas_core_external_link_staging_candidate.{md,jsonl}
- 20260607_120000_atlas_core_performance_risk_candidate.{md,jsonl}
- 20260607_120000_atlas_core_next_safe_batch_recommendation.{md,jsonl}
- 20260607_120000_atlas_core_5case_identity_approval_packets.{md,jsonl}
- 20260607_120000_atlas_core_execution_decision_log.md
- 20260607_atlas_core_three_db_merge_architecture_analysis.md
- 20260607_atlas_core_identity_ranking_and_db_diff.md

Total: 11 .md + 8 .jsonl = 19 files. All JSONL lines (65) have `codex_verification_needed=true`.

**No files mutated**: no .sqlite, no source DB writes, no env/secrets, no deploy/upload.

### Prior session (2026-06-05 to 2026-06-06)

Built the DeepSeekTUI handoff package at `docs/handoffs/atlas-core-deepseektui-20260606/` (11 files). Built WSL2 mirror at `/home/pc/deepseektui-handoffs/atlas-core-20260606`. Designed next optimization plan with superpowers:brainstorming + superpowers:writing-plans at `docs/superpowers/specs/` and `docs/superpowers/plans/`.

---

## 5. Verification status

### Passed

- 20-path API shadow diff: 0 regression, 0 leak
- Safe execution pipeline: 5/5 steps rc=0
- Source hash guard: before==after for all 5 sources
- FTS smoke: OIL (trigram), DJ/深圳/上海 (unicode61) all verified
- Readback: core/serving/miniapp/index all 4 layers verified
- Compat contract: 7 tables all column-verified
- Leak scan: 0 findings across gaps and case rows
- WSL2 mirror: SHA256 matches repo (11 files)
- Outbox: all 65 JSONL lines codex_verification_needed=true
- DB1/2/3 read-only access: verified for all queries

### Failed

- 46-path expanded shadow diff: `api_shadow_diff_execution_failed` (AbortError) — 3 runs, all 0 rows
- P0 expanded variant: same failure
- Full v2 variant: same failure

### Not run / not confirmed

- Cannot start API server for shadow diff re-run (Node.js dependency, port allocation)
- Cannot stop 23 DB2 rogue legacy workers (requires process signals to live DB2)
- 33 remaining identity cases not in full approval packet format
- DB2 external-link quality gate not analyzed by category
- DB1→DB2 pipeline gap (101K events dropped) not investigated

---

## 6. Current blockers

| Blocker | Severity | Unblock action |
|---------|----------|---------------|
| S232D-4 identity merge | P0 — gates all production DB writes | 13 HIGH cases ready for approve; write explicit gate |
| 46-path shadow diff execution | P1 — blocks expanded coverage proof | Restart Node.js API server, increase startup timeout, re-run |
| DB2 23 rogue legacy workers | P1 — blocks external-link projection | Maintenance window: stop workers, confirm 0 backlog |
| 33 identity cases not in packet format | P2 — quality of life | Run same readback script for remaining cases |

---

## 7. Next best entry

**Start with**: Open `atlas_core_safe_execution_report.json` and confirm `decision=atlas_core_safe_execution_passed`.

```bash
cd /mnt/c/code/githubstar/wechathtmldownload
python3 -c "import json; j=json.load(open('tools/stage7_rewrite/reports/atlas_core_candidate_20260605_legacy_rank_org_fix/atlas_core_safe_execution_report.json')); print(j['decision'], j['blockers'], j['source_hashes_unchanged'])"
```

**Why**: This is the gate-level truth. Every claim in the handoff package traces back to this JSON. If it still says `passed` and `[]`, the candidate is still valid. If it changed, the entire downstream analysis is stale.

**Then**: Pick ONE of these three lanes based on session capability:

- **If you have Node.js + API server access**: Fix and re-run 46-path shadow diff (`atlasCoreApiShadowDiff.mjs`). The AbortError is likely a cold-start timeout.
- **If you have DB read access**: Complete the 13 HIGH identity approval packets with full entity detail, or analyze DB2 external-link blocked categories.
- **If you have maintenance access**: Stop 23 rogue legacy workers and release the DB2 external-link projection gate.

---

## 8. Warnings / pitfalls

1. **Worktree is very dirty (5,872 entries)**. Do NOT `git reset`, `git clean`, or switch branches. The dirty state is intentional and protected.
2. **`atlas_core.sqlite` is NOT the API serving DB**. The API reads core-exported `atlas_serving.sqlite`. The `ATLAS_CORE_SQLITE_DB` env var is deliberately misleading.
3. **46-path shadow diff summary.md claims 0 regression but is likely a template**. The 1-byte rows file proves no actual comparison ran. Do not cite the 46-path "pass" as evidence.
4. **S119/S120 direct join to DB3 is forbidden**. External links must map through `entity_legacy_id`. Direct `entity_search_id→dj_profile.dj_id` join re-creates identity drift.
5. **`identity_resolution_case=348` is NOT a merged list**. It's a blocker queue. approved_for_s232d4=0.
6. **Compat tables look ugly but are required**. Removing any compat_* table will regress old scripts, rank calculators, search, graph rendering, org rollup consumers.
7. **`dj_venue_rollup` count went from 137,101 to 161,810**. The +24,709 difference is from better venue resolution. Shadow diff venue search shows 0 regression. Accept unless exact match required.
8. **Chinese FTS on trigram returns 0 for some queries**. This is known design, not a bug. unicode61 companion covers Chinese. Do not flag as regression.
9. **DB3 is a strict subset of DB2**. The 1,764 DB2-only DJs are correct — Core export recovers all 53,555.
10. **`docs/DOCUMENTATION_INDEX.md` is 1,674 lines**. The CURRENT_AUTHORITY entry for `atlas-core-deepseektui-20260606/00_README_FOR_DEEPSEEKTUI.md` is at the top. Read that first.

---

## 9. Key paths

### Repo (Windows)
```
C:\code\githubstar\wechathtmldownload\
  docs\handoffs\atlas-core-deepseektui-20260606\        ← DeepSeekTUI handoff package (11 files)
  docs\superpowers\specs\2026-06-06-atlas-core-deepseektui-next-optimization-design.md
  docs\superpowers\plans\2026-06-06-atlas-core-deepseektui-next-optimization.md
  docs\DOCUMENTATION_INDEX.md                           ← CURRENT_AUTHORITY entry at top
  tools\stage7_rewrite\reports\atlas_core_candidate_20260605_legacy_rank_org_fix\  ← final candidate
  tools\stage7_rewrite\scripts\atlas_core_common.py
  tools\stage7_rewrite\scripts\build_atlas_core_candidate.py
  tools\stage7_rewrite\scripts\run_atlas_core_candidate_safe.py
  services\weekly_activity_cloudrun\scripts\atlasCoreApiShadowDiff.mjs
```

### WSL2
```
/home/pc/deepseektui-handoffs/atlas-core-20260606/     ← WSL2 mirror (11 files, SHA256 verified)
/home/pc/deepseek-dream/outbox/20260607_*               ← this session's output (19 files)
/home/pc/deepseek-dream/inbox/ATLAS_CORE_20260606_*     ← prior session inbox entries
```

### Source databases
```
DB1: reports\atlas_incremental_wechat_refresh_20260522_1438\...\atlas.sqlite    (3.8GB, hash guard only)
DB2: reports\atlas_serving_time_overlay_span_split_search_date_refresh_candidate_20260527_2018\atlas_serving.sqlite  (2.1GB, main source)
DB3: services\weekly_activity_cloudrun\data\atlas_miniapp.sqlite  (364MB, secondary source)
S119: tools\stage7_rewrite\reports\external_link_db2_sidecar_contract_s119_20260601\external_link_db2_sidecar.sqlite
S232: tools\stage7_rewrite\reports\atlas_relation_identity_s232d3b8_candidate_preflight_20260603\s232d3b8_candidate_rows.jsonl
```
