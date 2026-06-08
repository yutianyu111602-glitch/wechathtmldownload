<!-- CODE_ALIGNMENT_2026_04_30_START -->
> Code alignment note (2026-04-30): this document was reviewed during the repository-wide docs/code sync. Treat `README.md`, `AGENTS.md`, `docs/CURRENT_CODE_MAP.md`, `docs/CLI_REFERENCE.md`, `docs/CONFIGURATION.md`, `docs/CODE_AUDIT.md`, and `docs/DOCUMENTATION_INDEX.md` as current code-aligned SSOT. Older dated handoffs/logs remain historical evidence and must be checked against current code before execution.
<!-- CODE_ALIGNMENT_2026_04_30_END -->

# PRD: WeChat Pipeline Super Long Run v1

**Date:** 2026-04-27
**Status:** FROZEN
**Source:** Night Watcher completion + Board Discussion

---

## 1. Project Background

Night Watcher completed 93,000 LLM release pack (D:\DDownload\_llm_release_v2). Next: downstream structured extraction, quality reports, graph candidate pack generation. Rawwechat MarkItDown 100% complete (8095/8095). This PRD unifies all plan scopes and establishes the execution baseline.

## 2. Current Facts

### 2.1 LLM Release Pack v2 (Primary Product)
| Field | Value |
|-------|-------|
| Path | D:\DDownload\_llm_release_v2 |
| Total articles | 93,000 |
| Ready | 81,425 |
| Review | 10,437 |
| Blocked | 1,138 |
| Clubs | 63 |
| Manifest | manifest.json (last written 2026-04-27 16:01) |
| Index | index.jsonl (93,000 lines) |

### 2.2 Rawwechat MD (Legacy, No Stale Repair)
| Field | Value |
|-------|-------|
| Path | D:\rawwechat_md |
| Total | 8,095 |
| Succeeded | 4,949 |
| Skipped | 3,146 |
| Failed | 0 |
| Queued | 0 |
| Running | 0 |
| Policy | Verification & archive only. No stale repair. |

### 2.3 Model
| Field | Value |
|-------|-------|
| Model | Qwen3.6-27B |
| Service | llama-swap:11434 |
| Temperature | 0.1 |
| Top-P | 0.9 |
| Max Tokens | 2048 |
| Context Limit | 8K |
| Known Issue | ~9.8K token articles fail on 3 prompts (8K limit) |
| Downstream Eval | 57/60 PASS, 95% success |

### 2.4 Safety
| Rule | Status |
|------|--------|
| D drive is 16T helium HDD | Guard enforced |
| No recursive scan D:\DDownload | Guard enforced |
| No recursive scan D:\aidata | Guard enforced |
| OCR locked to PaddleOCR | Locked |
| No EasyOCR fallback | Locked |
| No OpenRouter fallback | Locked |
| No Start-Process with `2>&1 \| Tee-Object` | Banned |

## 3. Extraction Scope

### 3.1 Ready Subset (US-002, US-003, US-004)
- Only process the 81,425 ready articles
- Review (10,437) goes to review queue
- Blocked (1,138) goes to blocked queue

### 3.2 Context Gate (US-001B) — Mandatory Before Any Batch
All articles must pass token estimation before entering the model:
- Normal queue: estimated_input + max_output <= context_limit
- Compress/truncate queue: 7K-12K tokens
- Long context queue: >12K tokens
- No blind retry on long articles

### 3.3 Non-Goals
- No stalled repair on rawwechat
- No retry on review/blocked articles
- No full 93K run before US-000, US-001, US-001B, US-002, US-003 pass
- No OpenClaw/AG/Hermes startup
- No production database writes
- No code refactoring (record as tech debt only)

## 4. Success Metrics
- 93,000 downstream extraction complete (ready subset only)
- Quality report generated
- Graph candidate pack generated
- Temp files cleaned
- Documentation unified
- Code quality baseline established
- GA monitor integrated
- Final report generated

## 5. Stop Conditions (All Stories)
- GPU OOM
- Model unavailable (3 retries max)
- D drive I/O spike detected
- Disk free space < 50GB
- Failure rate > 15%
- Same story fail 3x in a row
- Suspicious scan process detected
- final_pack process detected
- OpenClaw/AG process detected

---

## 6. OpenCode Execution Boundaries

OpenCode is the executor but operates under strict constraints:

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

---

## 7. User Stories

### US-000: Tooling Capability Audit
| Field | Value |
|-------|-------|
| Priority | 0 (pre-flight) |
| Status | queued |
| Owner | OpenCode |
| Goal | Verify all required CLI commands and scripts exist |
| Input | src/cli.ts, package.json, dist/cli.js |
| Output | tooling-audit-report.md, implementation-needed.md |
| Acceptance | All required commands registered or gaps documented |
| Stop Gates | None (read-only) |
| GA Checks | None (pre-flight) |
| Human Decision | Review audit report before proceeding |
| Forbidden | No production task execution |

### US-001: Baseline Freeze (Metadata Only)
| Field | Value |
|-------|-------|
| Priority | 1 |
| Status | queued |
| Owner | OpenCode |
| Goal | Freeze product snapshot metadata without full 93K hash |
| Input | manifest.json, index.jsonl, markitdown-batch-status.json |
| Output | baseline-snapshot.json (file sizes, mtimes, line counts, manifest hash) |
| Acceptance | Snapshot re-verifiable; no article body read; no recursive D scan |
| Stop Gates | D drive I/O spike, suspicious scan |
| GA Checks | Checkpoint last modified, D I/O, process list |
| Human Decision | Review baseline before US-001B |
| Forbidden | No full 93K hashing; no article body reading; no recursive D:\DDownload scan |

### US-001B: Context Gate & Long Article Policy
| Field | Value |
|-------|-------|
| Priority | 2 |
| Status | queued |
| Owner | OpenCode |
| Goal | Gate all articles by estimated token count before model batch |
| Input | 93,000 articles metadata + body length estimates |
| Output | normal_queue.jsonl, long_context_queue.jsonl, review_queue.jsonl, blocked_queue.jsonl, context-gate-report.md |
| Acceptance | Every article classified; evidence written per article; no long article re-enters normal batch |
| Stop Gates | D drive I/O spike, suspicious scan |
| GA Checks | Checkpoint, D I/O, model service status |
| Human Decision | Review gate report populations before US-002 |
| Forbidden | No full body reading of 93K; no model call; use length estimates |

### US-002: Downstream Dry-run 100 (Ready Only)
| Field | Value |
|-------|-------|
| Priority | 3 |
| Status | queued |
| Owner | OpenCode |
| Goal | Run structured extraction on 100 ready articles from normal_queue |
| Input | normal_queue.jsonl (first 100), Qwen3.6-27B |
| Output | dry-run-100.jsonl, dry-run-errors.jsonl |
| Acceptance | JSON valid rate >= 90%; no OOM/timeout; output lines = 100 |
| Stop Gates | GPU OOM, model unavailable, failure rate > 15% |
| GA Checks | Checkpoint growth, run log growth, D I/O, GPU VRAM |
| Human Decision | Review dry-run results before US-003 |
| Forbidden | No 1000 nor 93K batch |

### US-003: Downstream Smoke 1000 (Ready Only)
| Field | Value |
|-------|-------|
| Priority | 4 |
| Status | queued |
| Owner | OpenCode |
| Goal | Run 1000 article batch with checkpoint and resume capability |
| Input | normal_queue.jsonl (first 1000) |
| Output | smoke-1000.jsonl, smoke-checkpoints/, smoke-errors.jsonl |
| Acceptance | 1000 records; resume functional; error taxonomy populated; throughput >= 50/hr |
| Stop Gates | Same as US-002 |
| GA Checks | All runtime + business metrics |
| Human Decision | Review smoke results before US-004 |
| Forbidden | No 93K batch |

### US-004: Full Ready Subset Downstream Batch
| Field | Value |
|-------|-------|
| Priority | 5 |
| Status | queued |
| Owner | OpenCode |
| Goal | Full structured extraction on all normal_queue articles |
| Input | normal_queue.jsonl (all entries) |
| Output | full-downstream.jsonl, full-checkpoints/, full-errors.jsonl |
| Acceptance | Coverage >= 98%; failure rate < 5%; resume functional; checkpoint complete |
| Stop Gates | All standard gates + checkpoint interval enforcement |
| GA Checks | Full runtime + business + safety monitoring |
| Human Decision | Review before US-005 |
| Forbidden | No auto-retry on failed tasks |

### US-005: Review / Blocked Queue Report
| Field | Value |
|-------|-------|
| Priority | 6 |
| Status | queued |
| Owner | OpenCode |
| Goal | Generate statistics and classification report for review and blocked queues |
| Input | review_queue.jsonl, blocked_queue.jsonl |
| Output | queue-report.md, queue-stats.json |
| Acceptance | Accurate counts; reason breakdown; actionable categories |
| Stop Gates | None (read-only) |
| GA Checks | Checkpoint growth |
| Human Decision | Review before cleanup decisions |
| Forbidden | No automated processing of review/blocked items |

### US-006: Downstream Quality Report
| Field | Value |
|-------|-------|
| Priority | 7 |
| Status | queued |
| Owner | OpenCode |
| Goal | Statistical quality report on full extraction results |
| Input | full-downstream.jsonl |
| Output | quality-report.json, quality-charts/ |
| Acceptance | JSON parse rate, entity/event quality stats, failure distribution |
| Stop Gates | None (read-only report) |
| GA Checks | Checkpoint growth |
| Human Decision | Review quality before US-007 |
| Forbidden | No production database writes |

### US-007: Graph Candidate Pack Dry-run
| Field | Value |
|-------|-------|
| Priority | 8 |
| Status | queued |
| Owner | OpenCode |
| Goal | Generate entities/events/venues/djs/edges/evidence candidate pack |
| Input | full-downstream.jsonl, quality-report.json |
| Output | graph-candidate-pack/ (JSON/JSONL) |
| Acceptance | Entity dedup reasonable; relations traceable; conflict < 10%; no prod DB write |
| Stop Gates | None (read-only generation) |
| GA Checks | D I/O (graph generation can be heavy) |
| Human Decision | Review before any graph import |
| Forbidden | No production graph database write |

### US-008: Rawwechat Legacy Verification & Archive
| Field | Value |
|-------|-------|
| Priority | 9 |
| Status | queued |
| Owner | OpenCode |
| Goal | Verify rawwechat MD completeness and archive as frozen legacy |
| Input | D:\rawwechat_md, markitdown-batch-status.json |
| Output | rawwechat-verification-report.md, rawwechat-archive-manifest.json |
| Acceptance | 8095/8095 verified; no modification to status files; no stale repair |
| Stop Gates | D drive I/O spike |
| GA Checks | D I/O |
| Human Decision | Approve archive before any cleanup |
| Forbidden | No modification of markitdown-batch-status.json |

### US-009: Safety Policy Hardening
| Field | Value |
|-------|-------|
| Priority | 10 |
| Status | queued |
| Owner | OpenCode |
| Goal | Validate and harden all safety rules |
| Input | safety-policy.md, current environment |
| Output | safety-audit-report.md |
| Acceptance | All 12 guard rules verified; env locks confirmed; no violations |
| Stop Gates | None (audit only) |
| GA Checks | OCR env, suspicious processes |
| Human Decision | Review before signing off |
| Forbidden | No rule modification without human approval |

### US-010: GA Monitor Integration
| Field | Value |
|-------|-------|
| Priority | 11 |
| Status | queued |
| Owner | GA Agent (read-only) |
| Goal | Integrate read-only GA monitoring with periodic summaries |
| Input | All runtime state files |
| Output | GA_MONITOR_SUMMARY_*.md (every 10 min) |
| Acceptance | 9 checks complete; correct format; accurate alerts; no privilege escalation |
| Stop Gates | GA detects RED condition |
| GA Checks | Self-check (GA is the monitor) |
| Human Decision | Review first GA summary |
| Forbidden | No killing processes; no config changes; no task launches; no file deletion |

### US-011: Cleanup Dry-run Plan
| Field | Value |
|-------|-------|
| Priority | 12 |
| Status | queued |
| Owner | OpenCode |
| Goal | Plan cleanup of 27 tmp-* dirs + temp files without execution |
| Input | GLOBAL_DATA_INVENTORY.md (sections 9.1-9.5) |
| Output | cleanup-plan.md, cleanup-dry-run-log.txt |
| Acceptance | All items identified; impact assessed; no deletion executed |
| Stop Gates | None (planning only) |
| GA Checks | None |
| Human Decision | Approve plan before any deletion |
| Forbidden | No Remove-Item; no file deletion |

### US-012: Final Report and Handoff
| Field | Value |
|-------|-------|
| Priority | 13 |
| Status | queued |
| Owner | OpenCode |
| Goal | Generate final report, handoff, and next phase plan |
| Input | All prior US outputs |
| Output | FINAL_HANDOFF_*.md, NEXT_PHASE_PLAN.md, mem0 entries |
| Acceptance | All metrics traceable; next plan clear; mem0 recorded |
| Stop Gates | None (final step) |
| GA Checks | All final states confirmed |
| Human Decision | Sign off on handoff |
| Forbidden | No new task initiation |

