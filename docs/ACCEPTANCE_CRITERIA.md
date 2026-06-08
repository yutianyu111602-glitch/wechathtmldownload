<!-- CODE_ALIGNMENT_2026_04_30_START -->
> Code alignment note (2026-04-30): this document was reviewed during the repository-wide docs/code sync. Treat `README.md`, `AGENTS.md`, `docs/CURRENT_CODE_MAP.md`, `docs/CLI_REFERENCE.md`, `docs/CONFIGURATION.md`, `docs/CODE_AUDIT.md`, and `docs/DOCUMENTATION_INDEX.md` as current code-aligned SSOT. Older dated handoffs/logs remain historical evidence and must be checked against current code before execution.
<!-- CODE_ALIGNMENT_2026_04_30_END -->

# Acceptance Criteria — WeChat Pipeline Long Run

## 2026-05-07 Current Overlay

This acceptance checklist is the old control-plane skeleton checklist. Current 93k acceptance is tracked by:

- `docs\PROJECT_STATUS_2026-05-07.md`
- `tools\stage7_rewrite\WECHAT_93K_NEXT_AI_HANDOFF_2026-05-07.md`
- `tools\stage7_rewrite\SUPER_LONGRUN_ACTIVE_BOARD_2026-05-07.md`
- `D:\downstream_results\stage7_rewrite\longrun\STATUS_93K_PIPELINE\PIPELINE_STATUS_LATEST.md`

Current hard acceptance gates: wave recovery must finish archive/assets/process/audit; `LLM_INTAKE_MANIFEST_20260507` must rebuild with `0 blocked`; Stage7/Stage8 remain bounded canaries; `full93k`, `batch500`, production vector worker, Qdrant/Neo4j/PC DB batch writes, and broad Dajiala remain blocked until fresh authorization.

**Created:** 2026-04-27
**Model:** qwen3.6-max (planning)
**Status:** CONSOLIDATED from existing skeleton files
**Sources:**
- `docs/longrun-control-plane/11_ACCEPTANCE_CHECKLIST.md`
- `docs/longrun-control-plane/09_US000_TOOLING_CAPABILITY_AUDIT_PLAN.md`
- `docs/longrun/super-longrun-v1/01-PRD.md` (success criteria section)

---

## 1. Skeleton Creation Acceptance

### Files Created
- [x] docs/PRD.md
- [x] docs/RUNBOOK.md
- [x] docs/MODEL_POLICY.md
- [x] docs/GA_OPERATOR_GUIDE.md
- [x] docs/ACCEPTANCE_CRITERIA.md (this file)
- [x] docs/SKELETON_VERIFICATION.md
- [x] reports/INITIAL_ARCHITECTURE_PLAN_2026-04-27.md

### Content Checks
- [x] PRD defines control plane goals and non-goals
- [x] Runbook has startup, status, GREEN/AMBER/RED, escalation, pause/resume
- [x] GA Protocol: read-only mandate explicit, forbidden actions explicit
- [x] Model Policy: profile boundaries clear, Pro forbidden from execution
- [x] Local Registry: 4 models registered with paths, sizes, use recommendations
- [x] Evidence Pack: mandatory artifacts listed, formats defined
- [x] Handoff: template with all 10 required sections
- [x] Ralph Plan: re-enablement strategy, audit gate, no production connection
- [x] US-000 Plan: audit scope defined, gate to US-001 clear
- [x] Risk Register: 12 risks with mitigations

### Boundary Checks
- [x] No production task started
- [x] No US-001 or US-002 entered
- [x] No dry-run 100 executed
- [x] No D drive recursive scan
- [x] No OpenRouter used
- [x] No business files modified
- [x] deepseek-v4-pro NOT used for execution
- [x] GA Monitor defined as read-only

---

## 2. US-000 Tooling Capability Audit

### 2.1 OpenCode Tool Audit
- [ ] bash: file ops, git, npm scripts
- [ ] read: file reading (text, binary, directory)
- [ ] write: file creation
- [ ] edit: targeted string replacement
- [ ] glob: file pattern search
- [ ] grep: content search
- [ ] task: subagent launch
- [ ] webfetch: URL content retrieval
- [ ] skill: skill loading

### 2.2 Context-Mode Tool Audit
- [ ] ctx_execute: JavaScript/Python/shell sandbox
- [ ] ctx_execute_file: file processing without context load
- [ ] ctx_batch_execute: multi-command + search
- [ ] ctx_fetch_and_index: web fetch → index
- [ ] ctx_search: knowledge base search
- [ ] ctx_index: content indexing
- [ ] ctx_stats: context consumption stats

### 2.3 File Access Audit
- [ ] Read: project files, D:\DDownload\_llm_release_v2\manifest.json
- [ ] Read: D:\rawwechat_md\markitdown-batch-status.json
- [ ] Write: docs/ and artifacts/ only (not data dirs)
- [ ] No access: D:\DDownload recursive
- [ ] No access: D:\aidata recursive

### 2.4 Local Model Audit
- [ ] Qwen3.6-27B available at the current Stage7 endpoint in `tools\stage7_rewrite\config\default.yaml`
- [ ] Model responds to /v1/models
- [ ] Model responds to /v1/chat/completions (smoke test, 1 short prompt)

### 2.5 GA Monitor Audit
- [ ] Can read manifest.md
- [ ] Can read run log
- [ ] Can check disk/GPU
- [ ] Can detect suspicious processes
- [ ] Cannot write to data dirs
- [ ] Cannot kill processes

### 2.6 CLI Command Audit
- [ ] `node dist/cli.js --help` returns
- [ ] run-downstream-llm-batch registered
- [ ] build-graph-candidate-pack registered
- [ ] Missing commands documented: create-baseline-snapshot, generate-quality-report, context-gate

### Output
```
docs/longrun-control-plane/reports/US000_TOOLING_AUDIT_REPORT.md
```

### Gate
US-000 must pass ALL items before US-001 can start.
Failed items → document in implementation-needed.md.

---

## 3. US-001 Baseline Freeze Acceptance

- [ ] Snapshot re-verifiable
- [ ] No article body read
- [ ] No recursive D:\DDownload scan
- [ ] baseline-snapshot.json contains: file sizes, mtimes, line counts, manifest hash
- [ ] D drive I/O spike not detected
- [ ] No suspicious scan process detected

---

## 4. US-001B Context Gate Acceptance

- [ ] Every article classified (normal/long_context/review/blocked)
- [ ] Evidence written per article
- [ ] No long article re-enters normal batch
- [ ] context-gate-report.md generated
- [ ] D drive I/O spike not detected

---

## 5. US-002 Dry-run 100 Acceptance

- [ ] JSON valid rate >= 90%
- [ ] No OOM/timeout
- [ ] Output lines = 100
- [ ] dry-run-100.jsonl generated
- [ ] dry-run-errors.jsonl generated
- [ ] GPU OOM not detected
- [ ] Model available throughout
- [ ] Failure rate < 15%

---

## 6. US-003 Smoke 1000 Acceptance

- [ ] 1000 records
- [ ] Resume functional
- [ ] Error taxonomy populated
- [ ] Throughput >= 50/hr
- [ ] smoke-1000.jsonl generated
- [ ] smoke-checkpoints/ directory created
- [ ] smoke-errors.jsonl generated

---

## 7. US-004 Full Ready Subset Acceptance

- [ ] Coverage >= 98%
- [ ] Failure rate < 5%
- [ ] Resume functional
- [ ] Checkpoint complete
- [ ] full-downstream.jsonl generated
- [ ] full-checkpoints/ directory created
- [ ] full-errors.jsonl generated

---

## 8. US-005 Review/Blocked Queue Acceptance

- [ ] Accurate counts
- [ ] Reason breakdown
- [ ] Actionable categories
- [ ] queue-report.md generated
- [ ] queue-stats.json generated

---

## 9. US-006 Downstream Quality Report Acceptance

- [ ] JSON parse rate calculated
- [ ] Entity/event quality stats
- [ ] Failure distribution
- [ ] quality-report.json generated

---

## 10. US-007 Graph Candidate Pack Acceptance

- [ ] Entity dedup reasonable
- [ ] Relations traceable
- [ ] Conflict < 10%
- [ ] No prod DB write
- [ ] graph-candidate-pack/ directory created

---

## 11. US-008 Rawwechat Verification Acceptance

- [ ] 8095/8095 verified
- [ ] No modification to status files
- [ ] No stale repair
- [ ] rawwechat-verification-report.md generated
- [ ] rawwechat-archive-manifest.json generated

---

## 12. US-009 Safety Policy Hardening Acceptance

- [ ] All 12 guard rules verified
- [ ] Env locks confirmed
- [ ] No violations
- [ ] safety-audit-report.md generated

---

## 13. US-010 GA Monitor Integration Acceptance

- [ ] 9 checks complete
- [ ] Correct format
- [ ] Accurate alerts
- [ ] No privilege escalation
- [ ] GA_MONITOR_SUMMARY_*.md generated (every 10 min)

---

## 14. US-011 Cleanup Dry-run Plan Acceptance

- [ ] All items identified
- [ ] Impact assessed
- [ ] No deletion executed
- [ ] cleanup-plan.md generated
- [ ] cleanup-dry-run-log.txt generated

---

## 15. US-012 Final Report and Handoff Acceptance

- [ ] All metrics traceable
- [ ] Next plan clear
- [ ] mem0 recorded
- [ ] FINAL_HANDOFF_*.md generated
- [ ] NEXT_PHASE_PLAN.md generated

---

## 16. Final State

- [ ] Ready for US-000 Tooling Capability Audit
- [ ] Need Human: NO
- [ ] Production Tasks: 0
