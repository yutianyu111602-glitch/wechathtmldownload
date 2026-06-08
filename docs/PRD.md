<!-- CODE_ALIGNMENT_2026_04_30_START -->
> Code alignment note (2026-04-30): this document was reviewed during the repository-wide docs/code sync. Treat `README.md`, `AGENTS.md`, `docs/CURRENT_CODE_MAP.md`, `docs/CLI_REFERENCE.md`, `docs/CONFIGURATION.md`, `docs/CODE_AUDIT.md`, and `docs/DOCUMENTATION_INDEX.md` as current code-aligned SSOT. Older dated handoffs/logs remain historical evidence and must be checked against current code before execution.
<!-- CODE_ALIGNMENT_2026_04_30_END -->

# PRD — WeChat Pipeline Long Run Control Plane

## 2026-05-07 Current PRD Overlay

This PRD remains the governance baseline for long-running WeChat pipeline work. It is not the current execution cursor.

The active 2026-05-07 objective is narrower and more concrete:

- recover historical empty-link articles through supervised waves;
- keep captcha/platform/empty captures isolated;
- rebuild the LLM intake manifest after each audited wave;
- use OCR-enriched content where HTML is weak;
- validate Stage7 entity extraction and Stage8 vector JSONL canaries before any larger run;
- keep weekly activity recommendation as a separate lane until mptext/exporter session is refreshed.

Current status from the 2026-05-07 09:24 CST snapshot:

- OCR and latest review OCR are complete.
- Latest free recovery is complete: `721 recovered / 56 review / 32 blocked`.
- Stage7 canary, Stage7 batch50, Stage8 JSONL vector canary, and graph pack monitoring are complete.
- Active cursor: `FULL_EMPTY_LINK_RECOVERY_20260507\PROCESS_WAVE_0005`, `4/6` chunks complete; chunk `0004` archive is still running.
- Production `full93k`, `batch500`, production vector worker, Qdrant/Neo4j/PC DB batch writes, and broad Dajiala remain blocked without fresh explicit authorization.

**Created:** 2026-04-27
**Model:** qwen3.6-max (planning)
**Status:** CONSOLIDATED from existing skeleton files
**Sources:**
- `docs/longrun-control-plane/01_PRD.md`
- `docs/longrun/super-longrun-v1/01-PRD.md`
- `docs/longrun-control-plane/00_INDEX.md`

---

## 1. Product Goal

A governance layer for long-running WeChat Pipeline tasks that provides observability, handoff, pause/resume, and escalation without allowing models unrestricted autonomy.

The WeChat Pipeline Super Long Run processes 93,000 LLM release pack articles (D:\DDownload\_llm_release_v2) through downstream structured extraction, quality reports, and graph candidate pack generation. This PRD unifies all plan scopes and establishes the execution baseline.

## 2. Core Users

| User | Role | Interaction |
|------|------|-------------|
| Me (human) | Owner, approver | Review reports, approve escalations |
| OpenCode | Executor (builder profile) | Runs audited tasks, creates docs |
| OpenClaw | Frozen | Not active |
| GA Monitor | Read-only watcher | Observes, classifies, escalates |
| Qwen3.6-27B (local) | Local inference | Structured extraction, analysis |

## 3. Current Facts

### 3.1 LLM Release Pack v2
| Field | Value |
|-------|-------|
| Path | D:\DDownload\_llm_release_v2 |
| Total articles | 93,000 |
| Ready | 81,425 |
| Review | 10,437 |
| Blocked | 1,138 |
| Clubs | 63 |

### 3.2 Rawwechat MD (Legacy)
| Field | Value |
|-------|-------|
| Path | D:\rawwechat_md |
| Total | 8,095 |
| Succeeded | 4,949 |
| Skipped | 3,146 |
| Failed | 0 |
| Policy | Verification & archive only. No stale repair. |

### 3.3 Local Models (D:\models)
| Model | Size | Quant | Status |
|-------|------|-------|--------|
| Qwen3.6-27B | 15.66 GB | Q4_K_M | Active (llama-swap:11434) |
| Qwen3.6-35B-A3B-UD | 20.61 GB | Q4_K_M | Registered, not loaded |
| Qwen3.6-35B-A3B-IQ4_NL | 18.50 GB | IQ4_NL | Registered, not loaded |
| Gemma-4-31B | 17.40 GB | Q4_K_M | Experimental |

## 4. Goals

- Stable long task execution with checkpoints
- Observable: every task leaves evidence
- Escalatable: RED conditions trigger Pro analysis
- Handoff-ready: any agent can resume from checkpoint
- Pauseable/resumable: no lost state on interrupt
- Upgradable: profiles can evolve without breaking docs

## 5. Non-Goals

- NOT a production business system
- NOT a general-purpose agent platform
- NOT enabling models to operate without human gating
- NOT replacing manual pipeline commands
- NOT recursive scan of D:\DDownload or D:\aidata
- NOT starting OpenClaw/AG/Hermes as controller

## 6. Profile Boundaries

| Profile | Model | Use | Forbidden |
|---------|-------|-----|-----------|
| deepseek-builder | v4-pro | Docs, plans, skeleton | Production execution |
| deepseek-v4-pro | v4-pro | RED root cause analysis | File writes, batch execute, production |
| deepseek-v4-flash | v4-flash | Watch, monitoring, log summary | Decisions, config changes |
| deepseek-v4-flash-extended | v4-flash | AMBER review, checkpoint diff | RED analysis, decisions |
| qwen3.6-max | local | Architecture planning, PRD, task decomposition | Production batch execution |
| qwen3.6-27B | local GGUF | Structured extraction, analysis | Planning, config changes |

## 7. Extraction Scope

### 7.1 Ready Subset
- Only process the 81,425 ready articles
- Review (10,437) goes to review queue
- Blocked (1,138) goes to blocked queue

### 7.2 Context Gate
All articles must pass token estimation before entering the model:
- Normal queue: estimated_input + max_output <= context_limit
- Compress/truncate queue: 7K-12K tokens
- Long context queue: >12K tokens
- No blind retry on long articles

## 8. Success Criteria

- All skeleton docs complete
- US-000 audit executed and passed
- US-001 baseline captured
- GA monitor protocol operational
- 0 unauthorized production runs before US-002 gate
- 93,000 downstream extraction complete (ready subset only)
- Quality report generated
- Graph candidate pack generated
- Temp files cleaned
- Documentation unified

## 9. Stop Conditions

- GPU OOM
- Model unavailable (3 retries max)
- D drive I/O spike detected
- Disk free space < 50GB
- Failure rate > 15%
- Same story fail 3x in a row
- Suspicious scan process detected
- final_pack process detected
- OpenClaw/AG process detected

## 10. User Stories (13 total)

| ID | Name | Priority | Status |
|----|------|----------|--------|
| US-000 | Tooling Capability Audit | 0 (pre-flight) | queued |
| US-001 | Baseline Freeze (Metadata Only) | 1 | queued |
| US-001B | Context Gate & Long Article Policy | 2 | queued |
| US-002 | Downstream Dry-run 100 (Ready Only) | 3 | queued |
| US-003 | Downstream Smoke 1000 (Ready Only) | 4 | queued |
| US-004 | Full Ready Subset Downstream Batch | 5 | queued |
| US-005 | Review / Blocked Queue Report | 6 | queued |
| US-006 | Downstream Quality Report | 7 | queued |
| US-007 | Graph Candidate Pack Dry-run | 8 | queued |
| US-008 | Rawwechat Legacy Verification & Archive | 9 | queued |
| US-009 | Safety Policy Hardening | 10 | queued |
| US-010 | GA Monitor Integration | 11 | queued |
| US-011 | Cleanup Dry-run Plan | 12 | queued |
| US-012 | Final Report and Handoff | 13 | queued |

## 11. OpenCode Execution Boundaries

| Allowed | Forbidden |
|---------|-----------|
| Run pre-approved CLI commands | Start final_pack / OpenClaw / AG / Hermes |
| Execute read-only audit scripts | Start 93K full batch without passing all gates |
| Write reports and documentation | Delete data/log/lock/DB/product files |
| Create baseline snapshots | Modify D:\rawwechat_md\markitdown-batch-status.json |
| Run context gate classification | Recursive scan D:\DDownload or D:\aidata |
| Execute dry-run and smoke batches | Call external paid API for business extraction |
| Generate quality reports | Auto-fix failed business tasks |
| Build graph candidate packs (dry-run) | Let model run silently > 30 min without checkpoint |
| Verify rawwechat completeness | Create cron / scheduled tasks |
| Harden and audit safety rules | Git commit / push |
| Run cleanup planning (dry-run only) | Change OCR backend |
| Generate final handoff | Use OpenRouter fallback |

## 12. Risk Register (Top 12)

| # | Risk | Likelihood | Impact | Mitigation |
|---|------|------------|--------|------------|
| R1 | DeepSeek Pro timeout on escalation | Medium | High | Reduce output to 4096, 3-bullet summary |
| R2 | Pro misused as builder | Medium | High | Profile policy enforced in config |
| R3 | GA Monitor auto-repairs | Low | Critical | Protocol: read-only mandate |
| R4 | Recursive D drive scan | Medium | High | Scan guard in runbook |
| R5 | Local model VRAM exhaustion | Medium | Medium | One model at a time |
| R6 | Evidence pack incomplete | High | Medium | Mandatory checklist per task |
| R7 | context-mode batch_execute stalls | Medium | Medium | Timeout limits, split large batches |
| R8 | Profile config drift | Low | High | Config diff in every evidence pack |
| R9 | Silent context exhaustion | Medium | High | ctx_stats periodic check |
| R10 | Handoff ambiguity | Medium | Medium | Strict template, mandatory sections |
| R11 | GA false positives on powershell | Low | Low | Process filter: exclude self-matches |
| R12 | Disk space exhaustion mid-run | Low | Critical | Pre-run check ≥ 100GB, monitor every 10min |
