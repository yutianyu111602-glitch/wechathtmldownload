<!-- CODE_ALIGNMENT_2026_04_30_START -->
> Code alignment note (2026-04-30): this document was reviewed during the repository-wide docs/code sync. Treat `README.md`, `AGENTS.md`, `docs/CURRENT_CODE_MAP.md`, `docs/CLI_REFERENCE.md`, `docs/CONFIGURATION.md`, `docs/CODE_AUDIT.md`, and `docs/DOCUMENTATION_INDEX.md` as current code-aligned SSOT. Older dated handoffs/logs remain historical evidence and must be checked against current code before execution.
<!-- CODE_ALIGNMENT_2026_04_30_END -->

# Risk Register — Hermes WSL2 7-Day Longrun

**Version:** v1.0
**Date:** 2026-04-28

---

## Top 15 Risks

| # | Risk | Likelihood | Impact | Mitigation | Status |
|---|------|------------|--------|------------|--------|
| R1 | WeChat window minimized/lost | High | High | Auto-detect, try restore, RED if failed | OPEN |
| R2 | WeChat requires re-login/captcha | Medium | Critical | RED, wait for human | OPEN |
| R3 | deepseek-v4-pro API rate limit | Medium | High | Retry 3x, fallback to local Qwen | OPEN |
| R4 | WSL2 shutdown/crash | Low | Critical | Checkpoint every 30min, resume on restart | OPEN |
| R5 | D drive I/O overload (HDD) | Medium | Medium | Rate-limit capture, monitor Disk Time | OPEN |
| R6 | Hermes skill misoperates Windows UI | Medium | High | Whitelist commands, no mouse/keyboard auto | OPEN |
| R7 | mem0 service unavailable | Low | Medium | Local file fallback | OPEN |
| R8 | Qwen3.6-27B VRAM exhaustion | Medium | Medium | One model at a time, monitor VRAM | OPEN |
| R9 | Capture duplicate rate too high | Medium | Medium | Manifest dedup, skip existing | OPEN |
| R10 | Loopy-archiver pipeline stuck | Medium | Medium | Timeout detection, independent process | OPEN |
| R11 | Hermes context exhaustion | Medium | High | `/compress` periodic cleanup | OPEN |
| R12 | Evidence pack incomplete | Medium | Medium | Mandatory checklist per task | OPEN |
| R13 | Profile config drift | Low | High | Config diff in every evidence pack | OPEN |
| R14 | Handoff ambiguity | Medium | Medium | Strict template, mandatory sections | OPEN |
| R15 | Disk space exhaustion mid-run | Low | Critical | Pre-run check >= 100GB, monitor every 30min | OPEN |

---

## Risk Detail

### R1: WeChat Window Minimized/Lost

**Trigger:** WeChat window not found or minimized
**Detection:** Monitor check fails (WeChat window status)
**Response:**
1. Try to restore: `powershell.exe -Command "(Get-Process WeChat).MainWindowHandle"`
2. Try Alt+Tab: `powershell.exe -Command "Add-Type -AssemblyName System.Windows.Forms; [System.Windows.Forms.SendKeys]::SendWait('%{TAB}')"`
3. If still lost: Write RED report
**Owner:** Hermes Monitor
**Review:** Daily

### R2: WeChat Re-Login/Captcha

**Trigger:** WeChat shows login screen or captcha
**Detection:** Capture fails with "window not in expected state"
**Response:**
1. Stop capture immediately
2. Write RED report with screenshot (if possible)
3. Wait for human intervention
**Owner:** Human
**Review:** Immediate

### R3: deepseek-v4-pro API Rate Limit

**Trigger:** API returns 429 or timeout
**Detection:** Hermes model call fails
**Response:**
1. Retry 3x with exponential backoff (1s, 2s, 4s)
2. If still failing: Switch to local Qwen3.6-27B
3. Write AMBER report
**Owner:** Hermes
**Review:** Per occurrence

### R4: WSL2 Shutdown/Crash

**Trigger:** WSL2 not responding
**Detection:** Monitor check fails (WSL2 status)
**Response:**
1. Windows side: `wsl --shutdown && wsl`
2. Resume from latest checkpoint
3. Check `state/run-state.json`
**Owner:** Human / Windows scheduled task
**Review:** Per occurrence

### R5: D Drive I/O Overload

**Trigger:** Disk Time > 80% sustained
**Detection:** Monitor check (D drive I/O)
**Response:**
1. Pause capture
2. Wait for I/O to drop below 60%
3. Resume with reduced batch size
**Owner:** Hermes Monitor
**Review:** Every 30 min

### R6: Hermes Skill Misoperates Windows UI

**Trigger:** Unexpected window interaction
**Detection:** Capture output anomalies, wrong window affected
**Response:**
1. Stop all UI automation
2. Write RED report
3. Review skill configuration
**Owner:** Human
**Review:** Immediate

### R7: mem0 Service Unavailable

**Trigger:** mem0 API not responding
**Detection:** mem0 health check fails
**Response:**
1. Save learnings to local file: `reports/mem0-fallback-*.jsonl`
2. Retry mem0 every 10 min
3. When recovered, batch upload fallback memories
**Owner:** Hermes
**Review:** Every 10 min

### R8: Qwen3.6-27B VRAM Exhaustion

**Trigger:** Model OOM or slow response
**Detection:** Model health check fails, response time > 30s
**Response:**
1. Wait for VRAM to free
2. If persistent: Restart llama-swap
3. Write AMBER report
**Owner:** Hermes Monitor
**Review:** Every 30 min

### R9: Capture Duplicate Rate Too High

**Trigger:** > 30% of captures are duplicates
**Detection:** Manifest status analysis
**Response:**
1. Check if WeChat is showing same articles
2. Adjust scroll/page_idle_limit
3. Write AMBER report
**Owner:** Hermes
**Review:** Per capture run

### R10: Loopy-Archiver Pipeline Stuck

**Trigger:** No new entities/relationships for > 2 hours
**Detection:** Loopy DB timestamp check
**Response:**
1. Check loopy process status
2. Kill stuck process if needed
3. Restart from last checkpoint
**Owner:** Hermes
**Review:** Every 2 hours

### R11: Hermes Context Exhaustion

**Trigger:** Context window near limit
**Detection:** Hermes `/usage` shows > 80% context used
**Response:**
1. Run `/compress` to clean context
2. Save key info to mem0
3. Write checkpoint
**Owner:** Hermes
**Review:** Every session

### R12: Evidence Pack Incomplete

**Trigger:** Missing required evidence files
**Detection:** Post-task checklist
**Response:**
1. Identify missing evidence
2. Regenerate if possible
3. Document gap if not recoverable
**Owner:** Hermes
**Review:** Per task

### R13: Profile Config Drift

**Trigger:** Config changes not documented
**Detection:** Config diff check
**Response:**
1. Compare current vs baseline config
2. Document changes
3. Revert if unauthorized
**Owner:** Hermes Monitor
**Review:** Daily

### R14: Handoff Ambiguity

**Trigger:** Handoff missing required sections
**Detection:** Handoff template validation
**Response:**
1. Fill missing sections
2. Verify all required fields present
3. Update template if needed
**Owner:** Hermes
**Review:** Per handoff

### R15: Disk Space Exhaustion

**Trigger:** D drive free < 50GB
**Detection:** Monitor check (disk free)
**Response:**
1. Stop all writes immediately
2. Write RED report
3. Wait for human cleanup
**Owner:** Human
**Review:** Every 30 min

---

## Risk Review Schedule

| Frequency | Action |
|-----------|--------|
| Every 30 min | Monitor checks R1, R5, R8, R15 |
| Every 2 hours | Check R10, R11 |
| Daily | Review all risks, update status |
| Per task | Check R3, R6, R7, R9, R12, R13, R14 |
| Immediate | R2, R4, R6 |

---

**End of Risk Register. Next: `prd/hermes-7day.prd.json`**
