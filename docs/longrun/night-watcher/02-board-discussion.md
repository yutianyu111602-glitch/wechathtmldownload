<!-- CODE_ALIGNMENT_2026_04_30_START -->
> Code alignment note (2026-04-30): this document was reviewed during the repository-wide docs/code sync. Treat `README.md`, `AGENTS.md`, `docs/CURRENT_CODE_MAP.md`, `docs/CLI_REFERENCE.md`, `docs/CONFIGURATION.md`, `docs/CODE_AUDIT.md`, and `docs/DOCUMENTATION_INDEX.md` as current code-aligned SSOT. Older dated handoffs/logs remain historical evidence and must be checked against current code before execution.
<!-- CODE_ALIGNMENT_2026_04_30_END -->

# Night Watcher Board Discussion

**Date:** 2026-04-26  
**Rounds:** 3 (Facts → Conflicts → Decisions)  

---

## Round 1: Facts

### What we know for certain

1. Pipeline stages 0-3 (archive, process, export, OCR) are COMPLETE
2. final_pack was attempted and interrupted at 73.7% due to bash 60-min timeout
3. finalize-llm-pack has NO resume support in code (verified in src/cli.ts)
4. 34,370 backend=none poster_ocr.json files are NORMAL (articles without images)
5. Stage lock file exists and will block restart
6. Partial _llm_release exists with 68,733 articles across 49 clubs
7. Calibration tool runs 480 sequential LLM calls, no retry
8. Downstream eval tool runs 180 sequential LLM calls, no retry
9. 22 CLI commands exist in the project; key ones are: finalize-llm-pack, runQwenCalibrationSweep.mjs, runDownstreamEvalMatrix.mjs
10. System is healthy: 8.6TB disk free, 28GB RAM free, RTX 4090 with 20.9GB VRAM free

### What is uncertain

1. Whether the stage lock is stale or active (lock file exists but no pipeline process running)
2. Exact final_pack duration (extrapolated 90-120 min from 73.7% in 60 min)
3. Whether calibration will work first try with Qwen3.6-27B (cold load timeout possible)

---

## Round 2: Conflicts

### Conflict 1: Output directory strategy
- **Option A:** Clean _llm_release and restart to same path
  - Pro: All downstream docs reference _llm_release
  - Con: Requires destructive delete; violates safety rules
- **Option B:** Use _llm_release_v2 as new output directory
  - Pro: No deletion needed; old data preserved for audit
  - Con: Downstream docs need updating; user may wonder about old directory

**Decision: Option B** — Use _llm_release_v2. Safety > convenience. User can clean old directory when they return.

### Conflict 2: llama-swap restart policy
- **Option A:** Never restart (PLAN hard rule)
- **Option B:** Allow restart only for model service recovery

**Decision: Option B** — llama-swap is infrastructure, not a pipeline process. Restarting it is like restarting a database. Allow with documentation.

### Conflict 3: Disk alert threshold
- **Option A:** 5GB (RUNBOOK)
- **Option B:** 100GB (PRD)

**Decision: Both** — 100GB for pre-flight validation (YELLOW alert), 5GB for runtime emergency (RED alert). Document both levels clearly.

### Conflict 4: Monitoring interval
- **Option A:** 10 minutes (RUNBOOK)
- **Option B:** 30 minutes (HANDOFF)

**Decision: 10 minutes during active stages, 30 minutes during idle/waiting.** Adaptive monitoring.

---

## Round 3: Decisions

### D1: Execution Order (Frozen)

```
Phase 0: Environment Validation + Lock Cleanup (5 min)
Phase 1: final_pack with _llm_release_v2 (90-120 min)
Phase 2: qwen3.6_calibration (60-120 min)
Phase 3: downstream_matrix_50 (45 min - 2 hours)
Phase 4: checkpoint_stop + Final Report
```

### D2: Timeout Policy

| Stage | Timeout | Kill Policy |
|-------|---------|-------------|
| final_pack | 3 hours | Do NOT kill; log and wait |
| calibration | 3 hours | Do NOT kill; log and wait |
| downstream | 6 hours | Do NOT kill; log and wait |

### D3: Error Recovery Policy

| Error Type | Action |
|------------|--------|
| Stage lock blocks start | Delete lock file (stale, no process running) |
| Process crashes | Check outputs; if complete proceed, if not log and wait |
| Process stuck (>30 min idle) | Log ALERT; do NOT kill; wait for human |
| Disk <100GB | YELLOW warning; continue |
| Disk <5GB | RED; STOP everything |
| Model service down | Try restart llama-swap (up to 3 attempts, 5 min apart) |
| GPU OOM | STOP; log; wait for human |
| Calibration cold load timeout | Retry with 120s timeout; 3 attempts |

### D4: Logging Policy

- Heartbeat every 10 min during active stages
- Heartbeat every 30 min during idle
- All decisions logged to NIGHT_WATCHER_LOG_2026-04-22.md
- Stage completion logged to manifest.md run_state
- All monitoring commands recorded verbatim

### D5: Handoff Policy

- Write handoff after every story completion or failure
- Include: current phase, story status, system health, next action
- Any new agent must be able to resume from manifest.md + latest handoff
