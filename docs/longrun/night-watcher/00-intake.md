<!-- CODE_ALIGNMENT_2026_04_30_START -->
> Code alignment note (2026-04-30): this document was reviewed during the repository-wide docs/code sync. Treat `README.md`, `AGENTS.md`, `docs/CURRENT_CODE_MAP.md`, `docs/CLI_REFERENCE.md`, `docs/CONFIGURATION.md`, `docs/CODE_AUDIT.md`, and `docs/DOCUMENTATION_INDEX.md` as current code-aligned SSOT. Older dated handoffs/logs remain historical evidence and must be checked against current code before execution.
<!-- CODE_ALIGNMENT_2026_04_30_END -->

# Night Watcher Intake

**Date:** 2026-04-26  
**Mode:** Unattended longrun  

---

## Goal (Verifiable)

Complete the WeChat 100K pipeline from `final_pack` through `checkpoint_stop`, producing:

1. `D:/DDownload/_llm_release_v2/manifest.json` — parseable, total_articles > 90,000
2. `D:/DDownload/_llm_release_v2/index.jsonl` — >90,000 lines
3. `D:/DDownload/_llm_release_v2/checksums.sha256` — exists
4. `qwen3.6-recommended-params.json` — 4 profiles with temperature, top_p, max_tokens
5. `eval-matrix-results.jsonl` — >=150 lines
6. Final report notifying human

---

## Success Criteria

| Criterion | Measurement |
|-----------|-------------|
| All artifacts exist | File existence checks |
| No data loss | Article count _llm_release >= _llm_artifacts - 500 |
| Logs complete | Every stage has at least one log entry |
| Human notified | NOTIFICATION_PENDING.flag exists |

---

## Stop Conditions

- All 5 success criteria met
- Dangerous operation required
- Disk <5GB
- Same story fails 3 times
- Model service down after 3 retries
- Max 24 iterations

---

## Dangerous Boundaries (NEVER auto-execute)

1. `Remove-Item -Recurse -Force` on any D:/DDownload path
2. `git reset --hard` / `git clean`
3. Docker prune / volume deletion
4. Killing processes other than pipeline own processes
5. Running >500 LLM calls without human budget approval
6. Auto-substituting models (Qwen3.6-27B is the ONLY model for calibration)

---

## Current State

- export_llm: COMPLETE (93,508/93,761)
- ocr_poster: COMPLETE (93,000, 0% actual failure)
- final_pack: INTERRUPTED (73.7%, needs restart with _llm_release_v2)
- Stage lock: ACTIVE (must clean before restart)
- System: ALL GREEN (disk, memory, GPU, model)
