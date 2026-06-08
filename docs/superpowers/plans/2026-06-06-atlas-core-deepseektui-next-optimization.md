# Atlas Core DeepSeekTUI Next Optimization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make WSL2 DeepSeekTUI produce evidence-backed candidate packets for the next Atlas Core optimization round without opening any production write path.

**Architecture:** DeepSeekTUI is a read-only/candidate sidecar. It reads the verified handoff package and report-local artifacts, produces Markdown/JSONL candidate packets in `/home/pc/deepseek-dream/outbox/`, then Codex reviews one bounded claim group at a time. No task writes DB1/DB2/DB3, deploys, syncs, uploads, reviews, or releases.

**Tech Stack:** WSL2 Ubuntu, Markdown, JSONL, Python 3 read-only scripts, SQLite read-only inspection, existing Atlas Core report-local artifacts.

---

## File Structure

DeepSeek should read:

- `/home/pc/deepseektui-handoffs/atlas-core-20260606/START_HERE_FOR_DEEPSEEK_TUI.md`
- `/home/pc/deepseektui-handoffs/atlas-core-20260606/00_README_FOR_DEEPSEEKTUI.md`
- `/home/pc/deepseektui-handoffs/atlas-core-20260606/01_ACCEPTANCE_REPORT.md`
- `/home/pc/deepseektui-handoffs/atlas-core-20260606/03_NEXT_OPTIMIZATION_PLAN.md`
- `/mnt/c/code/githubstar/wechathtmldownload/docs/DOCUMENTATION_INDEX.md`
- `/mnt/c/code/githubstar/wechathtmldownload/docs/handoffs/HANDOFF_ATLAS_CORE_CANDIDATE_20260605.md`
- `/mnt/c/code/githubstar/wechathtmldownload/tools/stage7_rewrite/reports/atlas_core_candidate_20260605_legacy_rank_org_fix/atlas_core_safe_execution_report.json`
- `/mnt/c/code/githubstar/wechathtmldownload/tools/stage7_rewrite/reports/atlas_core_api_shadow_diff_20260605_legacy_rank_org_fix/atlas_core_api_shadow_diff_summary.md`

DeepSeek should write only:

- `/home/pc/deepseek-dream/outbox/YYYYMMDD_HHMMSS_atlas_core_<slug>_candidate.md`
- `/home/pc/deepseek-dream/outbox/YYYYMMDD_HHMMSS_atlas_core_<slug>_candidate.jsonl`

DeepSeek must not modify:

- `/mnt/c/code/githubstar/wechathtmldownload/**/*.sqlite`
- production `atlas_serving.sqlite`, `atlas_miniapp.sqlite`, `atlas_index.json.gz`
- DB1/DB2/DB3 production databases
- CloudBase/CloudRun/mini-program release files

## Task 1: Current Authority Packet

**Files:**
- Read: `/home/pc/deepseektui-handoffs/atlas-core-20260606/START_HERE_FOR_DEEPSEEK_TUI.md`
- Read: `/mnt/c/code/githubstar/wechathtmldownload/tools/stage7_rewrite/reports/atlas_core_candidate_20260605_legacy_rank_org_fix/atlas_core_safe_execution_report.json`
- Create: `/home/pc/deepseek-dream/outbox/YYYYMMDD_HHMMSS_atlas_core_current_authority_candidate.md`
- Create: `/home/pc/deepseek-dream/outbox/YYYYMMDD_HHMMSS_atlas_core_current_authority_candidate.jsonl`

- [ ] **Step 1: Confirm paths exist**

Run:

```bash
test -f /home/pc/deepseektui-handoffs/atlas-core-20260606/START_HERE_FOR_DEEPSEEK_TUI.md
test -f /mnt/c/code/githubstar/wechathtmldownload/tools/stage7_rewrite/reports/atlas_core_candidate_20260605_legacy_rank_org_fix/atlas_core_safe_execution_report.json
test -f /mnt/c/code/githubstar/wechathtmldownload/tools/stage7_rewrite/reports/atlas_core_api_shadow_diff_20260605_legacy_rank_org_fix/atlas_core_api_shadow_diff_summary.md
```

Expected: exit code `0`.

- [ ] **Step 2: Read safe execution fields**

Run:

```bash
cd /mnt/c/code/githubstar/wechathtmldownload
python3 - <<'PY'
import json
from pathlib import Path
p = Path("tools/stage7_rewrite/reports/atlas_core_candidate_20260605_legacy_rank_org_fix/atlas_core_safe_execution_report.json")
j = json.loads(p.read_text(encoding="utf-8"))
print("decision", j["decision"])
print("blockers", j.get("blockers"))
print("report_local_output_only", j["safety"]["report_local_output_only"])
print("production_db_write_executed", j["safety"]["production_db_write_executed"])
print("source_db_write_executed", j["safety"]["source_db_write_executed"])
print("source_hashes_unchanged", j["source_hashes_unchanged"])
PY
```

Expected:

```text
decision atlas_core_safe_execution_passed
blockers []
report_local_output_only True
production_db_write_executed False
source_db_write_executed False
source_hashes_unchanged True
```

- [ ] **Step 3: Write current authority candidate**

Create a Markdown packet with these exact sections:

```markdown
# Atlas Core Current Authority Candidate

## Confirmed

- Final candidate path: `/mnt/c/code/githubstar/wechathtmldownload/tools/stage7_rewrite/reports/atlas_core_candidate_20260605_legacy_rank_org_fix/`.
- Safe execution decision: `atlas_core_safe_execution_passed`.
- API shadow diff is report-local only.
- Production DB write executed: `false`.
- Source DB write executed: `false`.

## Blocked

- Production pointer switch is not approved.
- DB3 S232D-4 is not approved.
- Mini-program upload/review/release is not approved.

## Evidence Paths

- `/home/pc/deepseektui-handoffs/atlas-core-20260606/START_HERE_FOR_DEEPSEEK_TUI.md`
- `/mnt/c/code/githubstar/wechathtmldownload/tools/stage7_rewrite/reports/atlas_core_candidate_20260605_legacy_rank_org_fix/atlas_core_safe_execution_report.json`
- `/mnt/c/code/githubstar/wechathtmldownload/tools/stage7_rewrite/reports/atlas_core_api_shadow_diff_20260605_legacy_rank_org_fix/atlas_core_api_shadow_diff_summary.md`
```

- [ ] **Step 4: Write JSONL candidate**

Every line must include `codex_verification_needed=true`. Example:

```jsonl
{"type":"current_authority_candidate","claim":"Atlas Core final candidate is report-local and safe-execution passed.","evidence_paths":["/mnt/c/code/githubstar/wechathtmldownload/tools/stage7_rewrite/reports/atlas_core_candidate_20260605_legacy_rank_org_fix/atlas_core_safe_execution_report.json"],"codex_verification_needed":true}
{"type":"safety_note","claim":"Production pointer switch, DB3 S232D-4, deploy, upload, review, and release remain blocked.","evidence_paths":["/home/pc/deepseektui-handoffs/atlas-core-20260606/01_ACCEPTANCE_REPORT.md"],"codex_verification_needed":true}
```

## Task 2: Shadow Matrix Expansion Candidate

**Files:**
- Read: `/mnt/c/code/githubstar/wechathtmldownload/tools/stage7_rewrite/reports/atlas_core_api_shadow_diff_20260605_legacy_rank_org_fix/atlas_core_api_shadow_diff_summary.md`
- Read: `/mnt/c/code/githubstar/wechathtmldownload/tools/stage7_rewrite/reports/atlas_core_candidate_20260605_legacy_rank_org_fix/atlas_core_safe_execution_report.json`
- Create: `/home/pc/deepseek-dream/outbox/YYYYMMDD_HHMMSS_atlas_core_shadow_matrix_expansion_candidate.md`
- Create: `/home/pc/deepseek-dream/outbox/YYYYMMDD_HHMMSS_atlas_core_shadow_matrix_expansion_candidate.jsonl`

- [ ] **Step 1: Extract current covered paths**

Run:

```bash
sed -n '/## Paths/,$p' /mnt/c/code/githubstar/wechathtmldownload/tools/stage7_rewrite/reports/atlas_core_api_shadow_diff_20260605_legacy_rank_org_fix/atlas_core_api_shadow_diff_summary.md
```

Expected: table with `20` path ids and no findings.

- [ ] **Step 2: Draft added path categories**

Include these categories:

```text
DJ exact search: high-frequency, low-frequency, mixed-case, symbol-heavy, Chinese aliases.
Venue search: OIL, ALL, Dada, Elevator, POTENT, city-scoped venue names.
City event search: 深圳, 上海, 北京, 成都, 昆明, 杭州, 贵阳.
Organizer/label graph: rows that depend on dj_org_rollup.
Profile detail: profiles with many events, sparse profiles, redirect ids.
Source evidence lookup: source_ref/evidence_ref high-count and low-count samples.
Activity detail: events with many evidence refs and events with missing/blocked evidence.
```

- [ ] **Step 3: Add execution guard**

The candidate must state:

```text
This packet proposes a matrix only. It does not execute API calls. Codex must approve before running atlasCoreApiShadowDiff.mjs with expanded samples.
```

- [ ] **Step 4: Write JSONL candidate**

Use this shape:

```jsonl
{"type":"optimization_candidate","claim":"Expand API shadow diff with DJ, venue, city, organizer, profile, source evidence, and activity detail samples before production promotion.","evidence_paths":["/mnt/c/code/githubstar/wechathtmldownload/tools/stage7_rewrite/reports/atlas_core_api_shadow_diff_20260605_legacy_rank_org_fix/atlas_core_api_shadow_diff_summary.md"],"codex_verification_needed":true}
```

## Task 3: Legacy Compatibility Contract Candidate

**Files:**
- Read: `/home/pc/deepseektui-handoffs/atlas-core-20260606/01_ACCEPTANCE_REPORT.md`
- Read: `/mnt/c/code/githubstar/wechathtmldownload/tools/stage7_rewrite/reports/atlas_core_candidate_20260605_legacy_rank_org_fix/atlas_core_safe_execution_report.json`
- Create: `/home/pc/deepseek-dream/outbox/YYYYMMDD_HHMMSS_atlas_core_compat_contract_candidate.md`
- Create: `/home/pc/deepseek-dream/outbox/YYYYMMDD_HHMMSS_atlas_core_compat_contract_candidate.jsonl`

- [ ] **Step 1: Extract compat counts**

Run:

```bash
cd /mnt/c/code/githubstar/wechathtmldownload
python3 - <<'PY'
import json
from pathlib import Path
j = json.loads(Path("tools/stage7_rewrite/reports/atlas_core_candidate_20260605_legacy_rank_org_fix/atlas_core_safe_execution_report.json").read_text(encoding="utf-8"))
for k, v in sorted(j["readback"]["core"]["counts"].items()):
    if k.startswith("compat_"):
        print(k, v)
PY
```

Expected includes:

```text
compat_activity_event_detail 196
compat_activity_evidence_ref 2181
compat_canonical_subject 82878
compat_dj_org_rollup 323335
compat_dj_profile 53555
compat_graph_window_cache 53555
compat_search_document 590927
```

- [ ] **Step 2: Draft protected table contract**

The Markdown packet must list these serving tables as protected:

```text
canonical_subject
dj_profile
performance_event
dj_event
dj_relation_rollup
dj_venue_rollup
evidence_ref
search_document
search_document_fts
graph_window_cache
activity_event_detail
activity_evidence_ref
```

The packet must list these miniapp tables as protected:

```text
subject
dj_profile
dj_event
dj_collaborator
dj_venue
source_ref
dj_identity_redirect
dj_identity_profile_disposition
```

- [ ] **Step 3: Add removal guard**

The packet must state:

```text
Do not remove compat_* snapshots until every legacy consumer has a replacement contract and shadow diff proves no regression.
```

- [ ] **Step 4: Write JSONL candidate**

Use this shape:

```jsonl
{"type":"compat_contract_candidate","claim":"compat_* snapshots are required to protect old read-model fields, ranks, source counts, graph cache, and organizer rollups.","evidence_paths":["/home/pc/deepseektui-handoffs/atlas-core-20260606/01_ACCEPTANCE_REPORT.md","/mnt/c/code/githubstar/wechathtmldownload/tools/stage7_rewrite/reports/atlas_core_candidate_20260605_legacy_rank_org_fix/atlas_core_safe_execution_report.json"],"codex_verification_needed":true}
```

## Task 4: Identity Approval Packet Draft For 38 Source-Backed Cases

**Files:**
- Read: `/mnt/c/code/githubstar/wechathtmldownload/tools/stage7_rewrite/reports/atlas_core_candidate_20260605_legacy_rank_org_fix/identity_resolution_cases.jsonl`
- Create: `/home/pc/deepseek-dream/outbox/YYYYMMDD_HHMMSS_atlas_core_identity_38_approval_packet_candidate.md`
- Create: `/home/pc/deepseek-dream/outbox/YYYYMMDD_HHMMSS_atlas_core_identity_38_approval_packet_candidate.jsonl`

- [ ] **Step 1: Confirm case file exists**

Run:

```bash
test -f /mnt/c/code/githubstar/wechathtmldownload/tools/stage7_rewrite/reports/atlas_core_candidate_20260605_legacy_rank_org_fix/identity_resolution_cases.jsonl
wc -l /mnt/c/code/githubstar/wechathtmldownload/tools/stage7_rewrite/reports/atlas_core_candidate_20260605_legacy_rank_org_fix/identity_resolution_cases.jsonl
```

Expected: file exists, line count is `348`.

- [ ] **Step 2: Count lanes without writing DB**

Run:

```bash
cd /mnt/c/code/githubstar/wechathtmldownload
python3 - <<'PY'
import json
from collections import Counter
from pathlib import Path
p = Path("tools/stage7_rewrite/reports/atlas_core_candidate_20260605_legacy_rank_org_fix/identity_resolution_cases.jsonl")
c = Counter()
for line in p.read_text(encoding="utf-8").splitlines():
    if not line.strip():
        continue
    row = json.loads(line)
    c[row.get("lane", "")] += 1
print(dict(sorted(c.items())))
PY
```

Expected: counts align with `38` source-backed lane and remaining pending/manual/external evidence lanes. If field names differ, report `schema_observation` and do not infer approval.

- [ ] **Step 3: Draft approval packet schema**

For each of the 38 source-backed candidates, the packet design must require:

```text
case_id
group_id
normalized_name
candidate_entity_ids_json
legacy_ids
source_ref_ids
proposed_canonical_entity_id
proposed_redirect_entity_ids
accept_condition
reject_condition
defer_condition
needs_more_evidence_condition
fields_that_must_not_be_overwritten
evidence_paths
```

- [ ] **Step 4: Add hard write gate**

The packet must state:

```text
approved_for_s232d4_count remains 0. db_write_allowed_now_count remains 0. This packet is not approval to execute S232D-4.
```

## Task 5: External-Link Staging Candidate

**Files:**
- Read: `/home/pc/deepseektui-handoffs/atlas-core-20260606/01_ACCEPTANCE_REPORT.md`
- Read: `/mnt/c/code/githubstar/wechathtmldownload/tools/stage7_rewrite/reports/atlas_core_candidate_20260605_legacy_rank_org_fix/atlas_core_safe_execution_report.json`
- Create: `/home/pc/deepseek-dream/outbox/YYYYMMDD_HHMMSS_atlas_core_external_link_staging_candidate.md`
- Create: `/home/pc/deepseek-dream/outbox/YYYYMMDD_HHMMSS_atlas_core_external_link_staging_candidate.jsonl`

- [ ] **Step 1: Confirm external-link evidence count**

Run:

```bash
cd /mnt/c/code/githubstar/wechathtmldownload
python3 - <<'PY'
import json
from pathlib import Path
j = json.loads(Path("tools/stage7_rewrite/reports/atlas_core_candidate_20260605_legacy_rank_org_fix/atlas_core_safe_execution_report.json").read_text(encoding="utf-8"))
print("external_link_evidence", j["readback"]["core"]["counts"]["external_link_evidence"])
print("raw_url_columns", j["readback"]["core"]["external_link_raw_url_columns"])
PY
```

Expected:

```text
external_link_evidence 748
raw_url_columns []
```

- [ ] **Step 2: Draft staging state model**

Use only these statuses:

```text
candidate
blocked
accepted_for_graph
```

Require identity mapping through:

```text
entity_legacy_id
```

Forbidden mapping:

```text
S119/S120 entity_search_id -> DB3 dj_profile.dj_id direct join
```

- [ ] **Step 3: Write JSONL safety note**

Use this shape:

```jsonl
{"type":"external_link_staging_candidate","claim":"External links must map through entity_legacy_id and remain candidate/blocked/accepted_for_graph; raw URLs must not be emitted.","evidence_paths":["/home/pc/deepseektui-handoffs/atlas-core-20260606/01_ACCEPTANCE_REPORT.md","/mnt/c/code/githubstar/wechathtmldownload/tools/stage7_rewrite/reports/atlas_core_candidate_20260605_legacy_rank_org_fix/atlas_core_safe_execution_report.json"],"codex_verification_needed":true}
```

## Task 6: Performance And Rebuild Risk Candidate

**Files:**
- Read: `/home/pc/deepseektui-handoffs/atlas-core-20260606/02_EXECUTION_LOG.md`
- Read: `/home/pc/deepseektui-handoffs/atlas-core-20260606/06_HIGHLIGHTS_PITFALLS.md`
- Create: `/home/pc/deepseek-dream/outbox/YYYYMMDD_HHMMSS_atlas_core_performance_risk_candidate.md`
- Create: `/home/pc/deepseek-dream/outbox/YYYYMMDD_HHMMSS_atlas_core_performance_risk_candidate.jsonl`

- [ ] **Step 1: Confirm known fixed index risks**

Read:

```bash
grep -n "idx_graph_window_seed\|idx_search_document_subject\|NOT EXISTS" /home/pc/deepseektui-handoffs/atlas-core-20260606/02_EXECUTION_LOG.md /home/pc/deepseektui-handoffs/atlas-core-20260606/06_HIGHLIGHTS_PITFALLS.md
```

Expected: lines mention fixed `NOT EXISTS` fallback index risks.

- [ ] **Step 2: Draft remaining metrics**

The packet must recommend measuring:

```text
safe runner per-stage elapsed time
serving exporter per-table elapsed time
search_document_fts sample query timing
unicode61 companion sample query timing
graph_window_cache seed lookup timing
activity_evidence_ref lookup timing
row count and hash stability for compat tables
```

- [ ] **Step 3: Add no-code-change guard**

The packet must state:

```text
This packet identifies performance metrics only. It does not edit exporter code or run rebuild unless Codex approves a separate execution gate.
```

## Task 7: Return-To-Codex Recommendation Packet

**Files:**
- Read: all candidate packets created in Tasks 1-6
- Create: `/home/pc/deepseek-dream/outbox/YYYYMMDD_HHMMSS_atlas_core_next_safe_batch_recommendation_candidate.md`
- Create: `/home/pc/deepseek-dream/outbox/YYYYMMDD_HHMMSS_atlas_core_next_safe_batch_recommendation_candidate.jsonl`

- [ ] **Step 1: Summarize packets**

The Markdown packet must contain:

```markdown
# Atlas Core Next Safe Batch Recommendation

## Recommended next batch

P0 shadow matrix expansion first.

## Why

It protects old consumers before identity write planning and can be verified without production writes.

## Batch boundary

- No DB writes.
- No S232D-4.
- No deploy/upload/release.
- Only expand shadow diff sample design unless Codex approves execution.

## Needs Codex decision

- Which sample set to execute first.
- Whether identity approval packet should process all 38 source-backed cases or a smaller first 5-case canary.
```

- [ ] **Step 2: JSONL next question**

Use this shape:

```jsonl
{"type":"next_question","claim":"Codex should choose between executing P0 expanded shadow diff or drafting a 5-case identity approval canary first.","evidence_paths":["/home/pc/deepseek-dream/outbox/"],"codex_verification_needed":true}
```

## Final Verification

- [ ] **Step 1: List created packets**

Run:

```bash
find /home/pc/deepseek-dream/outbox -maxdepth 1 -type f -name '*atlas_core*candidate*' -printf '%TY-%Tm-%Td %TH:%TM %p\n' | sort | tail -20
```

Expected: Markdown/JSONL pairs for Tasks 1-7.

- [ ] **Step 2: Confirm no forbidden action was taken**

The final DeepSeek response must include:

```text
production_db_write_executed=false
source_db_write_executed=false
db3_s232d4_executed=false
cloudrun_deploy_executed=false
cloudbase_sync_executed=false
mini_program_upload_review_release_executed=false
secret_read_executed=false
```

## Execution Choice

Recommended first execution is inline DeepSeekTUI candidate generation for Tasks 1-3 only, then Codex review. Do not run all seven tasks unattended until Codex confirms the first three packet shapes are acceptable.
