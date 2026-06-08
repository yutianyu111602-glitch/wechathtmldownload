<!-- CODE_ALIGNMENT_2026_04_30_START -->
> Code alignment note (2026-04-30): this document was reviewed during the repository-wide docs/code sync. Treat `README.md`, `AGENTS.md`, `docs/CURRENT_CODE_MAP.md`, `docs/CLI_REFERENCE.md`, `docs/CONFIGURATION.md`, `docs/CODE_AUDIT.md`, and `docs/DOCUMENTATION_INDEX.md` as current code-aligned SSOT. Older dated handoffs/logs remain historical evidence and must be checked against current code before execution.
<!-- CODE_ALIGNMENT_2026_04_30_END -->

# GA Monitor Protocol

**Created:** 2026-04-27
**Status:** SKELETON

## Mandate

GA Monitor is the **read-only observation and classification layer** for long-running tasks.
It observes, classifies, summarizes, and escalates.
It does NOT repair, execute, or write business files.

## GA May Read

- manifest.md (current phase, story, heartbeat)
- run log (last N lines, growth rate)
- checkpoint files (existence, mtime, size)
- D: disk space (Get-Volume D)
- GPU status (nvidia-smi)
- model availability (curl localhost:11434)
- suspicious process count
- final_pack status (exists? running?)
- OpenClaw/AG status (process check)
- OCR env (WECHAT_OCR_COMMAND value)

## GA Must NOT

- Kill any process
- Start any production task
- Modify config files
- Delete files, locks, or state
- Clean up without human approval
- Recursive-scan D:\DDownload or D:\aidata
- Auto-fix anything
- Switch model profiles
- Call OpenClaw / AG / Hermes
- Write to business data paths

## GREEN / AMBER / RED Rules

### GREEN — All Clear
- All 9 monitors pass
- No anomalies
- Output: GA_MONITOR_SUMMARY: GREEN

### AMBER — Attention
- 1-2 monitors fail
- No critical impact
- Persists < 30 minutes
- Output: GA_MONITOR_SUMMARY: AMBER + which monitors
- If amber persists > 30min → escalate to Pro
- Pro validates: false positive or real issue

### RED — Critical
- GPU OOM, model unreachable, disk < 50GB
- Process idle > 60min
- 3+ monitors fail simultaneously
- Output: RED_ANALYSIS_REQUEST → deepseek-v4-pro

## Pro Escalation Protocol

```
flash watch detects RED
  → flash writes RED_ANALYSIS_REQUEST.md (evidence only, no analysis)
  → deepseek-v4-pro reads request + evidence
  → Pro writes RED_ANALYSIS.md:
      - Root cause
      - Impact assessment
      - Recommended actions (1-3)
      - Need Human: YES/NO
  → If Need Human: YES → stop, wait
  → If Need Human: NO + risk LOW → implement recommended action
```

## Pro Degradation

If deepseek-v4-pro times out on escalation:
1. Reduce analysis to 3 bullet points only
2. If still times out: output=4096 (not 8192)
3. If still fails: skip analysis, mark Need Human: YES
4. NEVER increase timeout past 300s
5. NEVER switch to builder profile for escalation

## False Positive Handling

Known false positives:
- powershell self-match in process list → filter with -ExcludeProperty
- transient GPU spike → require 3 consecutive failures
- network blip → retry curl 3 times with 5s delay

## Output Format

```
GA_MONITOR_SUMMARY_YYYY-MM-DD_HHmm.md
---
Status: GREEN|AMBER|RED
Monitors: passed/total
Anomalies: count
Escalated: YES/NO
Need Human: YES/NO
```
