# Atlas Core DeepSeekTUI Next Optimization Design

Date: 2026-06-06
Repo: `C:\code\githubstar\wechathtmldownload`
Audience: WSL2 DeepSeekTUI sidecar and Codex controller
Status: Accepted-by-user-delegation for planning; implementation remains report-local only

## Context

Atlas Core first-stage report-local candidate is ready for shadow/read-model work. The final candidate is:

```text
tools/stage7_rewrite/reports/atlas_core_candidate_20260605_legacy_rank_org_fix/
```

Confirmed state:

- `atlas_core_safe_execution_passed`
- API shadow diff: `20` paths, `0` regressions, `0` leaks
- source hashes unchanged
- production DB writes false
- DB3 S232D-4 writes false
- identity blockers still present: `348` cases, with `38` source-backed candidates and write-approved count `0`

DeepSeekTUI runs in WSL2 and should act as a long-running candidate analysis sidecar, not a production writer.

## Design Goal

Give DeepSeekTUI a bounded next-round work plan that improves Atlas Core confidence without opening any production write path.

The plan should produce evidence-backed candidate packets that Codex can review:

- wider API shadow coverage
- explicit legacy compatibility contract
- source-backed identity approval packet draft
- DB2/OpenClaw external-link staging analysis
- performance/readback risk notes

## Non-Goals

DeepSeekTUI must not:

- write DB1/DB2/DB3
- execute DB3 S232D-4
- switch production pointers
- deploy CloudRun/VPS/huaidj.club
- sync CloudBase
- upload/review/release the mini-program
- read secrets, `.env`, cookies, token files, browser profiles, or SSH keys
- scan `D:\`, `/mnt/d`, `D:\DDownload`, `D:\aidata`, or `/mnt/d/aidata` roots

## Approaches Considered

### Approach A: Shadow-Coverage First

DeepSeek starts by expanding the API/read-model coverage matrix before touching identity logic.

Pros:

- Lowest risk.
- Protects old consumers first.
- Finds compatibility gaps before DB3 merge planning.

Cons:

- Does not immediately reduce the 348 identity blocker.

### Approach B: Identity-Approval First

DeepSeek starts with the 38 source-backed identity cases and produces approval packet drafts.

Pros:

- Directly attacks the promotion blocker.
- Useful for DB3 S232D-4 planning.

Cons:

- Riskier if read model compatibility still has hidden regressions.
- Easy for a sidecar to overclaim merge readiness.

### Approach C: Promotion-Gate First

DeepSeek works backward from production promotion requirements.

Pros:

- Produces an executive checklist.

Cons:

- Too easy to blur report-local readiness with production readiness.
- Premature while identity and external-link staging remain blocked.

## Recommended Design

Use a hybrid of Approach A and B:

1. Start with authority confirmation and a current-state packet.
2. Expand shadow coverage and legacy compatibility contract.
3. Draft identity approval packets only for the 38 source-backed cases.
4. Analyze external-link staging through `entity_legacy_id`, not direct DB3 joins.
5. Return a single next safe batch recommendation to Codex.

This preserves the no-production-write boundary while moving the real blockers forward.

## Workstreams

### Workstream P0: Current Authority Confirmation

DeepSeek reads the handoff package, safe execution report, API shadow diff summary, and documentation index. It produces a `current_authority_candidate` packet.

Success criteria:

- final candidate path is correct
- safety flags are quoted from evidence
- no production readiness is claimed

### Workstream P1: Shadow Matrix Expansion

DeepSeek proposes a larger path matrix covering DJ, venue, city, organizer, label, graph seed, activity evidence, and source lookup paths.

Success criteria:

- every proposed path has a reason
- every proposed sample has a source table or existing API route
- no endpoint execution is required unless Codex approves

### Workstream P2: Legacy Compatibility Contract

DeepSeek identifies which legacy fields/tables must be protected because old scripts consume them.

Success criteria:

- covers `canonical_subject`, `dj_profile`, `performance_event`, `dj_event`, `dj_relation_rollup`, `dj_venue_rollup`, `evidence_ref`, `search_document`, `search_document_fts`, `graph_window_cache`, `activity_event_detail`, `activity_evidence_ref`
- covers miniapp `subject`, `dj_profile`, `dj_event`, `dj_collaborator`, `dj_venue`, `source_ref`, redirects, dispositions
- calls out compat snapshots that must not be removed

### Workstream P3: Identity Approval Packet Draft

DeepSeek reads `identity_resolution_cases.jsonl` and creates a packet design for only the `38` source-backed candidates.

Success criteria:

- `approved_for_s232d4_count` remains `0`
- every case has accept/reject/defer/needs-more-evidence criteria
- no blank-field overwrite is allowed

### Workstream P4: External-Link Staging Map

DeepSeek analyzes how S119/S120 external links should enter `external_link_evidence` and `entity_legacy_id`.

Success criteria:

- no raw URL output
- no direct join from `entity_search_id` to DB3 `dj_profile.dj_id`
- every link status is `candidate`, `blocked`, or `accepted_for_graph`

### Workstream P5: Performance and Rebuild Risk Notes

DeepSeek identifies readback/performance risks without changing code.

Success criteria:

- notes existing index fixes
- lists remaining timing/readback metrics to add
- flags unindexed fallback patterns only as candidates

## Output Contract

DeepSeek writes candidate packets to:

```text
/home/pc/deepseek-dream/outbox/
```

Every packet pair:

```text
YYYYMMDD_HHMMSS_atlas_core_<slug>_candidate.md
YYYYMMDD_HHMMSS_atlas_core_<slug>_candidate.jsonl
```

Every JSONL factual record includes:

```json
{"codex_verification_needed": true, "evidence_paths": ["..."]}
```

Allowed record types:

- `current_authority_candidate`
- `optimization_candidate`
- `compat_contract_candidate`
- `approval_packet_candidate`
- `external_link_staging_candidate`
- `performance_risk_candidate`
- `safety_note`
- `next_question`

## Stop Gates

DeepSeek stops and reports if:

- candidate path is missing
- safe execution decision is not `atlas_core_safe_execution_passed`
- source hashes changed
- any report says production/source DB write executed
- a needed artifact is missing
- a command would require secrets or production writes
- WSL dependencies are missing

## Acceptance

This design is accepted only for DeepSeekTUI planning and candidate-packet generation. It does not approve code changes, database writes, production pointer changes, deployment, or mini-program release.
