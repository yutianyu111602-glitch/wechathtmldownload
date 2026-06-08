<!-- CODE_ALIGNMENT_2026_04_30_START -->
> Code alignment note (2026-04-30): this document was reviewed during the repository-wide docs/code sync. Treat `README.md`, `AGENTS.md`, `docs/CURRENT_CODE_MAP.md`, `docs/CLI_REFERENCE.md`, `docs/CONFIGURATION.md`, `docs/CODE_AUDIT.md`, and `docs/DOCUMENTATION_INDEX.md` as current code-aligned SSOT. Older dated handoffs/logs remain historical evidence and must be checked against current code before execution.
<!-- CODE_ALIGNMENT_2026_04_30_END -->

# Runbook — Super Long Run v1

**Date:** 2026-04-27
**Usage:** Step-by-step execution guide for each story

---

## Quick Start

```powershell
# 1. Verify environment
powershell -ExecutionPolicy Bypass -File tools/super-longrun/validate-no-dangerous-scan.ps1
curl http://127.0.0.1:11434/v1/models

# 2. Start from current cursor
# Check manifest.md -> run_state.next_resume_cursor
```

## US-000: Tooling Capability Audit

```powershell
powershell -ExecutionPolicy Bypass -File tools/super-longrun/collect-tooling-capability.ps1
```
- [ ] Check reports/tooling-audit-report.md
- [ ] Review missing commands list
- [ ] HUMAN GATE: Approve or request command implementation

## US-001: Baseline Freeze

```powershell
powershell -ExecutionPolicy Bypass -File tools/super-longrun/collect-baseline-metadata.ps1
```
- [ ] Check baseline/baseline-snapshot.json
- [ ] Verify: files_size, mtimes, line counts, manifest hash match
- [ ] HUMAN GATE: Confirm baseline integrity

## US-001B: Context Gate

```powershell
powershell -ExecutionPolicy Bypass -File tools/super-longrun/context-gate-plan.ps1
```
- [ ] Check queues/*.jsonl files exist
- [ ] Review context-gate-report.md
- [ ] Verify normal_queue. count + compress_queue. count + long_context_queue. count = 93,000 - review - blocked
- [ ] HUMAN GATE: Confirm gate classification

## US-002: Dry-run 100

```powershell
# Pre-flight
powershell -ExecutionPolicy Bypass -File tools/super-longrun/validate-no-dangerous-scan.ps1

# Create output dir
mkdir -p docs/longrun/super-longrun-v1/output/dry-run-100

# Run
node dist/cli.js run-downstream-llm-batch `
  --inputDir D:/DDownload/_llm_release_v2 `
  --queuePath docs/longrun/super-longrun-v1/queues/normal_queue.jsonl `
  --outputDir docs/longrun/super-longrun-v1/output/dry-run-100 `
  --sampleSize 100 `
  --modelAlias Qwen3.6-27B `
  --temperature 0.1 --topP 0.9 --maxTokens 2048 --timeoutMs 180000
```
- [ ] Output: 100 JSONL lines
- [ ] Valid rate >= 90%
- [ ] No OOM, no runaway timeout
- [ ] HUMAN GATE: Approve to proceed

## US-003: Smoke 1000

```powershell
mkdir -p docs/longrun/super-longrun-v1/output/smoke-1000
mkdir -p docs/longrun/super-longrun-v1/output/smoke-1000/checkpoints

node dist/cli.js run-downstream-llm-batch `
  --inputDir D:/DDownload/_llm_release_v2 `
  --queuePath docs/longrun/super-longrun-v1/queues/normal_queue.jsonl `
  --outputDir docs/longrun/super-longrun-v1/output/smoke-1000 `
  --sampleSize 1000 `
  --modelAlias Qwen3.6-27B `
  --temperature 0.1 --topP 0.9 --maxTokens 2048 --timeoutMs 180000 `
  --enableCheckpoint `
  --checkpointDir docs/longrun/super-longrun-v1/output/smoke-1000/checkpoints
```
- [ ] Output: 1000 JSONL records
- [ ] Resume test: Ctrl+C mid-run, re-run with --resume
- [ ] Throughput >= 50/hr
- [ ] HUMAN GATE: Approve to proceed

## US-004: Full Ready Batch

```powershell
mkdir -p docs/longrun/super-longrun-v1/output/full-downstream
mkdir -p docs/longrun/super-longrun-v1/output/full-downstream/checkpoints

node dist/cli.js run-downstream-llm-batch `
  --inputDir D:/DDownload/_llm_release_v2 `
  --queuePath docs/longrun/super-longrun-v1/queues/normal_queue.jsonl `
  --outputDir docs/longrun/super-longrun-v1/output/full-downstream `
  --modelAlias Qwen3.6-27B `
  --temperature 0.1 --topP 0.9 --maxTokens 2048 --timeoutMs 180000 `
  --enableCheckpoint `
  --checkpointDir docs/longrun/super-longrun-v1/output/full-downstream/checkpoints `
  --checkpointInterval 500
```
- [ ] Coverage >= 98%
- [ ] Failure rate < 5%
- [ ] Checkpoint every 500

## US-005: Review/Blocked Report

Read-only analysis. Generate queue-report.md from review_queue.jsonl + blocked_queue.jsonl.

## US-006: Quality Report

```powershell
# Read full-downstream.jsonl, generate stats
node -e "..." > quality-report.json
```

## US-007: Graph Candidate Pack

```powershell
node dist/cli.js build-graph-candidate-pack `
  --inputDir docs/longrun/super-longrun-v1/output/full-downstream `
  --outputDir docs/longrun/super-longrun-v1/output/graph-candidate-pack `
  --dryRun
```

## US-008: Rawwechat Verification

```powershell
# Read-only verification
Get-Content D:/rawwechat_md/markitdown-batch-status.json | ConvertFrom-Json
# Verify: total=8095, failed=0, running=0, queued=0
```

## US-009: Safety Audit

Run all safety policy checks. Generate safety-audit-report.md.

## US-010: GA Monitor

```powershell
# Start GA monitoring (separate terminal)
# See 04-ga-monitor-spec.md
```

## US-011: Cleanup Plan

Generate cleanup-plan.md. No deletion.

## US-012: Final Handoff

Generate FINAL_HANDOFF_*.md, NEXT_PHASE_PLAN.md.
