<!-- CODE_ALIGNMENT_2026_04_30_START -->
> Code alignment note (2026-04-30): this document was reviewed during the repository-wide docs/code sync. Treat `README.md`, `AGENTS.md`, `docs/CURRENT_CODE_MAP.md`, `docs/CLI_REFERENCE.md`, `docs/CONFIGURATION.md`, `docs/CODE_AUDIT.md`, and `docs/DOCUMENTATION_INDEX.md` as current code-aligned SSOT. Older dated handoffs/logs remain historical evidence and must be checked against current code before execution.
<!-- CODE_ALIGNMENT_2026_04_30_END -->

# Night Watcher Evidence Map

**Date:** 2026-04-26  
**Categories:** Document Facts, Code Logic, Test/Verification, Risks/Conflicts, SSOT Path  

---

## 1. Document Facts

| Fact | Source | Confidence |
|------|--------|------------|
| export_llm completed 93,508/93,761 | export-llm-status.json | HIGH |
| ocr_poster completed 93,000 poster_ocr.json | HANDOFF analysis | HIGH |
| 34,370 backend=none files are NORMAL (no images) | Full analysis of all 34,370 files | CERTAIN |
| 30/31 corrupted OCR files repaired | repairCorruptedOcr.mjs run log | HIGH |
| 1 GIF file (44KW/00Nk9wyYNVncXXdGoBoiw) unrepaired | HANDOFF | HIGH |
| final_pack reached 73.7% before timeout | Direct observation | CERTAIN |
| final_pack took ~60 min for 73.7% | Wall clock measurement | CERTAIN |
| Estimated full final_pack: 90-120 min | Extrapolation from 73.7% in 60 min | HIGH |
| Stage lock file exists at D:\DDownload\.wechat-live-stage-lock.json | Data inventory scan | CERTAIN |
| download_ready_queue.jsonl has 93,761 lines | Data inventory scan | CERTAIN |
| _llm_md has 93,000 .md files across 63 clubs | Data inventory scan | CERTAIN |
| Log gap: 04-24 03:38 to 04-26 (undocumented period) | NIGHT_WATCHER_LOG gap | CERTAIN |

## 2. Code Business Logic

| Fact | Source | Confidence |
|------|--------|------------|
| finalize-llm-pack has NO resume/limit/offset | src/cli.ts:947-975, no args read | CERTAIN |
| finalize-llm-pack copies 6 files per article | finalizeLlmPack.ts:33-40 | CERTAIN |
| Final step: SHA-256 checksums of all output files | finalizeLlmPack.ts + checksums.ts | CERTAIN |
| No progress output during final_pack | No console.log in finalizeLlmPack | CERTAIN |
| Calibration sweep: 4 profiles x 3 prompts x 2 rounds x 20 samples = 480 calls | runQwenCalibrationSweep.mjs defaults | CERTAIN |
| Downstream eval: 3 models x 3 prompts x 1 round x 20 samples = 180 calls | runDownstreamEvalMatrix.mjs defaults | CERTAIN |
| Both tools are sequential (no concurrency) | Both use for-loop, no Promise.all for calls | CERTAIN |
| Neither tool has retry logic | Both have single-attempt try/catch | CERTAIN |
| 22 CLI commands total | src/cli.ts enumeration | CERTAIN |
| Live stage lock: 7-day stale timeout | liveStageLock.ts:33 | CERTAIN |
| Production path detection: regex /^[A-Za-z]:\\\\DDownload/i | liveStageLock.ts:44-56 | CERTAIN |

## 3. Test and Verification Gates

| Gate | How to Verify | Status |
|------|--------------|--------|
| final_pack completeness | manifest.json + index.jsonl + checksums.sha256 exist | PENDING |
| Index line count | (Get-Content index.jsonl).Count >= 90000 | PENDING |
| Calibration output | qwen3.6-recommended-params.json exists with 4 profiles | PENDING |
| Downstream output | eval-matrix-results.jsonl exists with >=150 lines | PENDING |
| System health | Disk >5GB, model responds at :11434, GPU available | PASSING |

## 4. Risks and Conflicts

| Risk | Probability | Impact | Mitigation |
|------|-------------|--------|------------|
| final_pack timeout again | Medium | High | 3-hour timeout + background process |
| Stage lock blocks restart | High (lock exists!) | High | Delete lock file before starting |
| Qwen3.6-27B cold load timeout | High | Medium | 120s first-call timeout |
| Calibration 2+ hours | Medium | Low | Expected; run overnight |
| Disk fills during checksums | Low | High | Monitor every 30min |
| Process stuck (no progress) | Medium | Medium | 30-min idle detection |
| 7 docs with contradictions | Resolved | Low | This manifest is SSOT |

## 5. SSOT / Documentation Path

```
docs/longrun/night-watcher/manifest.md  ← SINGLE ENTRY POINT
  ├── 00-intake.md                       ← Goals and success criteria
  ├── 01-evidence-map.md                 ← This file
  ├── 02-board-discussion.md             ← Convergence decisions
  ├── 03-prd.md                          ← Frozen requirements
  ├── 04-prd.json                        ← Ralph stories
  ├── 05-execution-plan.md               ← Step-by-step
  └── loops/loop-001-handoff.md          ← Current state
```

Historical docs preserved but superseded:
- NIGHT_WATCHER_PLAN_2026-04-26.md → See 03-prd.md
- PRD_NIGHT_WATCHER_2026-04-26.md → See 03-prd.md
- EXEC_PLAN_NIGHT_WATCHER_2026-04-26.md → See 05-execution-plan.md
- HANDOFF_2026-04-26_OCR_ACCEPTANCE.md → See loops/loop-001-handoff.md
