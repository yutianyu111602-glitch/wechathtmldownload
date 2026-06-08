<!-- CODE_ALIGNMENT_2026_04_30_START -->
> Code alignment note (2026-04-30): this document was reviewed during the repository-wide docs/code sync. Treat `README.md`, `AGENTS.md`, `docs/CURRENT_CODE_MAP.md`, `docs/CLI_REFERENCE.md`, `docs/CONFIGURATION.md`, `docs/CODE_AUDIT.md`, and `docs/DOCUMENTATION_INDEX.md` as current code-aligned SSOT. Older dated handoffs/logs remain historical evidence and must be checked against current code before execution.
<!-- CODE_ALIGNMENT_2026_04_30_END -->

# Execution Plan — Super Long Run v1

**Date:** 2026-04-27
**Status:** READY
**Execution Mode:** Direct CLI, foreground PowerShell, visible logs

---

## 1. Execution Strategy

### 1.1 Runtime
- Direct CLI execution (no OpenClaw cron)
- Foreground PowerShell (no Start-Process wrapper)
- Visible log output (Ctrl+C interruptible)
- Checkpoint persistence (resume-capable)

### 1.2 Failure Budget
- failure_budget=3 (max 3 fix attempts per story)
- Major checkpoint every 3 stories
- Stop gate reached -> immediate stop and handoff

### 1.3 Model Parameters
| Param | Value |
|-------|-------|
| Model | Qwen3.6-27B |
| Endpoint | http://127.0.0.1:11434/v1 |
| Temperature | 0.1 |
| Top-P | 0.9 |
| Max Tokens | 2048 |
| Timeout | 180,000 ms |

### 1.4 Hard Bans
1. No recursive scan D:\DDownload / D:\aidata / /mnt/d/*
2. No auto-delete lock / auto-fix business tasks
3. No auto-write production DB
4. No OpenClaw / AG / Hermes as main controller
5. No Stage 0-6 re-run
6. No Mac M3 Pro / vector model introduction

---

## 2. Story Execution Sequence

### Phase 0: Pre-Flight (US-000)
```
node tools/super-longrun/collect-tooling-capability.ps1
```
Verification: Check `docs/longrun/super-longrun-v1/reports/tooling-audit-report.md` exists.

### Phase 1: Baseline (US-001)
```
node tools/super-longrun/collect-baseline-metadata.ps1
```
Verification: Check `docs/longrun/super-longrun-v1/baseline/baseline-snapshot.json` exists.

### Phase 2: Context Gate (US-001B)
```
node tools/super-longrun/context-gate-plan.ps1
```
Verification: Check `normal_queue.jsonl`, `long_context_queue.jsonl`, `review_queue.jsonl`, `blocked_queue.jsonl` exist.

### Phase 3: Dry-run 100 (US-002)
```
node dist/cli.js run-downstream-llm-batch `
  --inputDir D:/DDownload/_llm_release_v2 `
  --queuePath docs/longrun/super-longrun-v1/queues/normal_queue.jsonl `
  --outputDir docs/longrun/super-longrun-v1/output/dry-run-100 `
  --sampleSize 100 `
  --modelAlias Qwen3.6-27B `
  --temperature 0.1 `
  --topP 0.9 `
  --maxTokens 2048 `
  --timeoutMs 180000
```
Verification: 100 JSONL lines, valid rate >= 90%.

### Phase 4: Smoke 1000 (US-003)
```
node dist/cli.js run-downstream-llm-batch `
  --inputDir D:/DDownload/_llm_release_v2 `
  --queuePath docs/longrun/super-longrun-v1/queues/normal_queue.jsonl `
  --outputDir docs/longrun/super-longrun-v1/output/smoke-1000 `
  --sampleSize 1000 `
  --modelAlias Qwen3.6-27B `
  --temperature 0.1 `
  --topP 0.9 `
  --maxTokens 2048 `
  --timeoutMs 180000 `
  --enableCheckpoint `
  --checkpointDir docs/longrun/super-longrun-v1/output/smoke-1000/checkpoints
```
Verification: 1000 records, resume functional, throughput >= 50/hr.

### Phase 5: Full Ready Batch (US-004)
```
node dist/cli.js run-downstream-llm-batch `
  --inputDir D:/DDownload/_llm_release_v2 `
  --queuePath docs/longrun/super-longrun-v1/queues/normal_queue.jsonl `
  --outputDir docs/longrun/super-longrun-v1/output/full-downstream `
  --modelAlias Qwen3.6-27B `
  --temperature 0.1 `
  --topP 0.9 `
  --maxTokens 2048 `
  --timeoutMs 180000 `
  --enableCheckpoint `
  --checkpointDir docs/longrun/super-longrun-v1/output/full-downstream/checkpoints `
  --checkpointInterval 500
```
Verification: Coverage >= 98%, failure rate < 5%.

### Phase 6-12: Remaining Stories
- US-005: Queue report (read-only script)
- US-006: Quality report (read-only script)
- US-007: Graph candidate pack (dry-run)
- US-008: Rawwechat verification (read-only)
- US-009: Safety audit (read-only)
- US-010: GA monitor (periodic, read-only)
- US-011: Cleanup plan (planning only)
- US-012: Final report (document generation)

---

## 3. Checkpoint Strategy

| Type | Frequency | Contents |
|------|-----------|----------|
| Minor | Every story | progress.json update, manifest.md update, loop handoff |
| Major | Every 3 stories | Risk re-check, test strategy re-check, PRD re-check, scorecard |

## 4. Recovery Rules
- Resume from latest checkpoint, never restart
- Max 3 fix attempts per story, then handoff
- Status file corruption -> human audit, not auto-rebuild

## 5. Output Directory Map
| Product | Path |
|---------|------|
| Baseline | baseline/ |
| Queues | queues/ |
| Dry-run 100 | output/dry-run-100/ |
| Smoke 1000 | output/smoke-1000/ |
| Full downstream | output/full-downstream/ |
| Quality report | output/quality-report/ |
| Graph candidate | output/graph-candidate-pack/ |
| Reports | reports/ |
