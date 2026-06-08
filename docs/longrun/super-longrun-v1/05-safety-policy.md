<!-- CODE_ALIGNMENT_2026_04_30_START -->
> Code alignment note (2026-04-30): this document was reviewed during the repository-wide docs/code sync. Treat `README.md`, `AGENTS.md`, `docs/CURRENT_CODE_MAP.md`, `docs/CLI_REFERENCE.md`, `docs/CONFIGURATION.md`, `docs/CODE_AUDIT.md`, and `docs/DOCUMENTATION_INDEX.md` as current code-aligned SSOT. Older dated handoffs/logs remain historical evidence and must be checked against current code before execution.
<!-- CODE_ALIGNMENT_2026_04_30_END -->

# Safety Policy — Super Long Run v1

**Date:** 2026-04-27
**Status:** ENFORCED
**Violations:** RED condition, immediate stop

---

## 1. HDD Scan Guard

| Rule | Enforcement |
|------|-------------|
| No recursive scan D:\DDownload | `validate-no-dangerous-scan.ps1` pre-flight |
| No recursive scan D:\aidata | Same validator |
| No find /mnt/d/DDownload | Same validator |
| No find /mnt/d/aidata | Same validator |
| No rg /mnt/d/DDownload | Same validator |
| No rg /mnt/d/aidata | Same validator |
| No grep -R /mnt/d | Same validator |
| No du -sh /mnt/d | Same validator |
| No ls -R /mnt/d | Same validator |
| D drive is 16T helium HDD | Fixed hardware constraint |

## 2. OCR Backend Lock

| Rule | Enforcement |
|------|-------------|
| WECHAT_OCR_COMMAND = tools/ocr-image-paddle.ps1 | Env check at start |
| OCR_GPU_REQUIRED = true | Env check at start |
| OCR_ALLOW_FALLBACK = false | Env check at start |
| No EasyOCR fallback | Hard lock |
| No auto-switch OCR backend | Hard lock |
| PaddleOCR unavailable -> fail fast | No fallback attempt |

## 3. Process Safety

| Rule | Enforcement |
|------|-------------|
| No Start-Process with `2>&1 \| Tee-Object` | Code review |
| All background tasks must self-log | Script convention |
| Foreground PowerShell only for production | Execution policy |

## 4. Provider Safety

| Rule | Enforcement |
|------|-------------|
| No OpenRouter fallback | Hard lock |
| No auto-switch API provider | Hard lock |
| DeepSeek official only via api.deepseek.com | Provider check |
| Qwen3.6 local only via llama-swap:11434 | Provider check |

## 5. Agent Safety

| Rule | Enforcement |
|------|-------------|
| OpenClaw frozen | Process check |
| AG frozen | Process check |
| Hermes not used | Process check |
| No auto-start any of the above | Pre-flight check |
| No cron for OpenClaw | Pre-flight check |

## 6. Silent Longrun Ban

| Rule | Enforcement |
|------|-------------|
| No model running unattended > 30 min without checkpoint | Checkpoint age check |
| No auto-restart of failed batch | Start gate check |
| All long tasks must have progress.json + run.log | Output check |

## 7. Cleanup Safety

| Rule | Enforcement |
|------|-------------|
| No auto cleanup | Human approval required |
| No Remove-Item on data/log/lock/DB | Command audit |
| Cleanup must be dry-run first | US-011 requirement |

## 8. Production Write Safety

| Rule | Enforcement |
|------|-------------|
| No production write without dry-run | US-002 prerequisite |
| No rawwechat status mutation without backup | US-008 requirement |
| No full 93K run before US-000/001/001B/002/003 pass | Gate sequence |

## 9. File Mutation Safety

| Rule | Enforcement |
|------|-------------|
| No modification of D:\rawwechat_md\markitdown-batch-status.json | Read-only access only |
| No modification of D:\DDownload\_llm_release_v2\ | Read-only access only |
| No deletion of any data/log/lock/DB/product | Remove-Item audit |

## 10. Scan Validation Script

Run `tools/super-longrun/validate-no-dangerous-scan.ps1` before any US that touches D drive. This script checks for:
- Active find processes targeting /mnt/d
- Active rg/grep processes targeting /mnt/d
- Active Get-ChildItem -Recurse targeting D:\DDownload or D:\aidata
- Returns PASS (safe) or FAIL (dangerous scan detected)
