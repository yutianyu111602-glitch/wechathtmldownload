<!-- CODE_ALIGNMENT_2026_04_30_START -->
> Code alignment note (2026-04-30): this document was reviewed during the repository-wide docs/code sync. Treat `README.md`, `AGENTS.md`, `docs/CURRENT_CODE_MAP.md`, `docs/CLI_REFERENCE.md`, `docs/CONFIGURATION.md`, `docs/CODE_AUDIT.md`, and `docs/DOCUMENTATION_INDEX.md` as current code-aligned SSOT. Older dated handoffs/logs remain historical evidence and must be checked against current code before execution.
<!-- CODE_ALIGNMENT_2026_04_30_END -->

# Risk Register

**Created:** 2026-04-27
**Status:** SKELETON

| # | Risk | Likelihood | Impact | Mitigation |
|---|------|------------|--------|------------|
| R1 | DeepSeek Pro timeout on escalation | Medium | High | Reduce output to 4096, 3-bullet summary, fallback to Need Human |
| R2 | Pro misused as builder | Medium | High | Profile policy enforced in config, forbidden actions documented |
| R3 | GA Monitor auto-repairs | Low | Critical | Protocol: read-only mandate, no write permissions to data dirs |
| R4 | Recursive D drive scan | Medium | High | Scan guard in runbook, explicit forbidden commands list |
| R5 | Local model VRAM exhaustion | Medium | Medium | One model at a time, monitor VRAM before load |
| R6 | Evidence pack incomplete | High | Medium | Mandatory checklist per task, verification before "done" |
| R7 | context-mode batch_execute stalls | Medium | Medium | Timeout limits, split large batches, avoid PowerShell in sandbox |
| R8 | Profile config drift | Low | High | config diff in every evidence pack, periodic audit |
| R9 | Silent context exhaustion | Medium | High | ctx_stats periodic check, flash watch for response degradation |
| R10 | Handoff ambiguity | Medium | Medium | Strict template, mandatory sections, evidence paths required |
| R11 | GA false positives on powershell | Low | Low | Process filter: exclude known self-matches |
| R12 | Disk space exhaustion mid-run | Low | Critical | Pre-run check ≥ 100GB, monitor every 10min, RED if < 50GB |

## Risk Levels

| Level | Action |
|-------|--------|
| Critical | Stop immediately, escalate to Pro, Need Human: YES |
| High | Trigger RED, escalate to Pro |
| Medium | Log, continue monitoring, escalate if persists |
| Low | Log, no action needed |
