<!-- CODE_ALIGNMENT_2026_04_30_START -->
> Code alignment note (2026-04-30): this document was reviewed during the repository-wide docs/code sync. Treat `README.md`, `AGENTS.md`, `docs/CURRENT_CODE_MAP.md`, `docs/CLI_REFERENCE.md`, `docs/CONFIGURATION.md`, `docs/CODE_AUDIT.md`, and `docs/DOCUMENTATION_INDEX.md` as current code-aligned SSOT. Older dated handoffs/logs remain historical evidence and must be checked against current code before execution.
<!-- CODE_ALIGNMENT_2026_04_30_END -->

# Operations Manual — Super Long Run v1

**Date:** 2026-04-27
**Role:** OpenCode Executor Reference

---

## 1. Pre-Start Checklist

Before starting any US, verify:
- [ ] D drive free space >= 100 GB
- [ ] Model service responding at http://127.0.0.1:11434/v1/models
- [ ] No suspicious process scanning D:\DDownload or D:\aidata
- [ ] No final_pack process running
- [ ] No OpenClaw/AG/Hermes process running
- [ ] OCR env = PaddleOCR (WECHAT_OCR_COMMAND=tools/ocr-image-paddle.ps1)
- [ ] node dist/cli.js --help works
- [ ] Previous US outputs verified (if not US-000)

## 2. How to Run Each US

### US-000: Tooling Capability Audit
```powershell
powershell -ExecutionPolicy Bypass -File tools/super-longrun/collect-tooling-capability.ps1
```
Output: `reports/tooling-audit-report.md`

### US-001: Baseline Freeze
```powershell
powershell -ExecutionPolicy Bypass -File tools/super-longrun/collect-baseline-metadata.ps1
```
Output: `baseline/baseline-snapshot.json`

### US-001B: Context Gate
```powershell
powershell -ExecutionPolicy Bypass -File tools/super-longrun/context-gate-plan.ps1
```
Output: `queues/normal_queue.jsonl`, `long_context_queue.jsonl`, etc.

### US-002: Dry-run 100
```powershell
node dist/cli.js run-downstream-llm-batch `
  --inputDir D:/DDownload/_llm_release_v2 `
  --queuePath docs/longrun/super-longrun-v1/queues/normal_queue.jsonl `
  --outputDir docs/longrun/super-longrun-v1/output/dry-run-100 `
  --sampleSize 100 `
  --modelAlias Qwen3.6-27B `
  --temperature 0.1 --topP 0.9 --maxTokens 2048 --timeoutMs 180000
```

### US-003: Smoke 1000
Same pattern as US-002, --sampleSize 1000, with --enableCheckpoint.

### US-004: Full Batch
Same pattern, no --sampleSize, with --checkpointInterval 500.

### US-005-US-012
Refer to `02-execution-plan.md` phases 6-12. Most are read-only scripts.

## 3. Go/No-Go Gates

| Gate | Condition | Action |
|------|-----------|--------|
| US-000 -> US-001 | All required commands documented | Human approves |
| US-001 -> US-001B | Baseline verified | Human approves |
| US-001B -> US-002 | Queue populations reviewed | Human approves |
| US-002 -> US-003 | Dry-run: valid >= 90% | Human approves |
| US-003 -> US-004 | Smoke: throughput >= 50/hr | Human approves |

## 4. Progress & Error Conventions

### progress.json
```json
{
  "phase": "Phase 1",
  "story_id": "US-001",
  "status": "in_progress",
  "started_at": "iso8601",
  "updated_at": "iso8601",
  "failure_count": 0,
  "notes": ""
}
```

### errors.jsonl
Each line: `{"story":"US-002","article_id":"...","error_type":"timeout|parse|oom","message":"...","timestamp":"iso8601"}`

## 5. RED / AMBER / GREEN

| State | Condition | Response |
|-------|-----------|----------|
| GREEN | Progressing, checkpoint updated, D normal | Continue |
| AMBER | 1 delayed checkpoint, temp high D I/O | Flag, do not escalate |
| RED | 2 missed checkpoints, D scan detected, forbidden process | STOP. Handoff. No auto-fix. |

## 6. GA Monitor Access
GA reads these files ONLY:
- `progress.json` (checkpoint timestamp)
- `run.log` (size, last write time)
- D drive I/O (Get-Volume metrics)
- Process list (suspicious names)
- OCR env variable
- `errors.jsonl` (count)

GA writes: `reports/GA_MONITOR_SUMMARY_*.md` only.

## 7. Handoff Template
See `templates/handoff-template.md`.

## 8. Rollback Principles
- Never delete data files
- Never modify D:\rawwechat_md\markitdown-batch-status.json
- Never modify D:\DDownload\_llm_release_v2\
- Restore from backup if needed, otherwise human audit

## 9. Forbidden Actions (Permanent)
1. Remove-Item on any data/log/lock/DB/product
2. Modify D:\rawwechat_md\markitdown-batch-status.json
3. Change OCR backend
4. Use OpenRouter
5. Create cron / scheduled task
6. Auto-retry failed business tasks
7. Git commit / push
8. Call external paid API for business extraction
9. Let model run silently for extended periods
10. Start final_pack / OpenClaw / AG / Hermes
