<!-- CODE_ALIGNMENT_2026_04_30_START -->
> Code alignment note (2026-04-30): this document was reviewed during the repository-wide docs/code sync. Treat `README.md`, `AGENTS.md`, `docs/CURRENT_CODE_MAP.md`, `docs/CLI_REFERENCE.md`, `docs/CONFIGURATION.md`, `docs/CODE_AUDIT.md`, and `docs/DOCUMENTATION_INDEX.md` as current code-aligned SSOT. Older dated handoffs/logs remain historical evidence and must be checked against current code before execution.
<!-- CODE_ALIGNMENT_2026_04_30_END -->

# GA Operator Guide — WeChat Pipeline Long Run

## 2026-05-07 Current Overlay

This guide is a historical read-only monitor protocol. The active monitor surface for the 93k recovery line is:

```powershell
Set-Location C:\code\githubstar\wechathtmldownload\tools\stage7_rewrite
python .\scripts\show_93k_pipeline_status.py --out-dir D:\downstream_results\stage7_rewrite\longrun\STATUS_93K_PIPELINE
```

For the current Stage7 lane, model health follows `tools\stage7_rewrite\config\default.yaml`: OpenAI-compatible endpoint `http://192.168.128.1:11434`, model `Qwen3.6-27B`. Older localhost checks in archived monitor docs are evidence only unless revalidated.

**Created:** 2026-04-27
**Model:** qwen3.6-max (planning)
**Status:** CONSOLIDATED from existing skeleton files
**Sources:**
- `docs/longrun-control-plane/03_GA_MONITOR_PROTOCOL.md`
- `docs/longrun-control-plane/06_EVIDENCE_PACK_SPEC.md`
- `docs/longrun-control-plane/07_HANDOFF_SPEC.md`
- `docs/longrun-control-plane/10_RISK_REGISTER.md`

---

## 1. GA Mandate

GA Monitor is the **read-only observation and classification layer** for long-running tasks.

**GA May:**
- Observe, classify, summarize, escalate
- Read manifest.md, run log, checkpoint files
- Check D: disk space, GPU status, model availability
- Detect suspicious processes
- Check final_pack status, OpenClaw/AG status, OCR env

**GA Must NOT:**
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

## 2. 9 Monitor Checks

| # | Monitor | Check | GREEN | AMBER | RED |
|---|---------|-------|-------|-------|-----|
| 1 | D drive recursive scan | Process cmdline | No DDownload/aidata recurse | Suspicious keywords | DDownload + Recurse in cmdline |
| 2 | final_pack process | Process exists | Not running | N/A | Running |
| 3 | OpenClaw auto-start | Process exists | Not running | Residual (user-launched) | Running + not user-launched |
| 4 | OCR backend drift | WECHAT_OCR_COMMAND | = PaddleOCR | N/A | ≠ PaddleOCR |
| 5 | D drive I/O >80% | Get-Volume D | < 80% busy | 1 round > 80% | 2+ consecutive rounds > 80% |
| 6 | Checkpoint stale | Checkpoint mtime | Updated < 30min ago | N/A | > 30 min no update |
| 7 | Model service | current Stage7 endpoint responds | Responding | 1-2 retries needed | Unreachable 3x |
| 8 | GPU VRAM | nvidia-smi | > 2GB free | < 2GB free (not OOM) | OOM |
| 9 | Disk space | Get-Volume D | > 100GB | 50-100GB | < 50GB |

## 3. GREEN / AMBER / RED Rules

### GREEN — All Clear
- All 9 monitors pass
- No anomalies
- Output: `GA_MONITOR_SUMMARY: GREEN`

### AMBER — Attention
- 1-2 monitors fail
- No critical impact
- Persists < 30 minutes
- Output: `GA_MONITOR_SUMMARY: AMBER` + which monitors
- If amber persists > 30min → escalate to Pro
- Pro validates: false positive or real issue

### RED — Critical
- GPU OOM, model unreachable, disk < 50GB
- Process idle > 60min
- 3+ monitors fail simultaneously
- Output: `RED_ANALYSIS_REQUEST` → deepseek-v4-pro

## 4. Pro Escalation Protocol

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

### Pro Degradation
If deepseek-v4-pro times out on escalation:
1. Reduce analysis to 3 bullet points only
2. If still times out: output=4096 (not 8192)
3. If still fails: skip analysis, mark Need Human: YES
4. NEVER increase timeout past 300s
5. NEVER switch to builder profile for escalation

### False Positive Handling
- powershell self-match in process list → filter with -ExcludeProperty
- transient GPU spike → require 3 consecutive failures
- network blip → retry curl 3 times with 5s delay

## 5. Output Format

```
GA_MONITOR_SUMMARY_YYYY-MM-DD_HHmm.md
---
Status: GREEN|AMBER|RED
Monitors: passed/total
Anomalies: count
Escalated: YES/NO
Need Human: YES/NO
```

## 6. Evidence Pack Requirements

Every long-run task must produce a complete evidence pack. No task is "done" without this.

### Mandatory Artifacts
| Artifact | Format | Description |
|----------|--------|-------------|
| checkpoint | JSON | Current story, progress, failures, timestamp |
| run log | Markdown | Timestamped event log, decisions, anomalies |
| final report | Markdown | Summary, results, metrics, next steps |
| config diff | Diff/text | What config changed during this run |
| model/profile snapshot | YAML/JSON | Which profile was active, params |
| command transcript | Text | Exact commands executed (copy-pasteable) |
| failure reason | Text | If failed: root cause, attempts, decision |
| Need Human assessment | Text | Clear YES/NO with reasoning |

### Optional Artifacts
| Artifact | When Required |
|----------|---------------|
| RED analysis | RED events only |
| scorecard | Every 3 stories |
| GA monitor summary | Every monitor cycle |
| handoff | On pause/stop/complete |

## 7. Handoff Specification

Every handoff must contain these 10 sections:

1. **Current Goal** — One sentence
2. **Completed** — Bullet list with evidence paths
3. **In Progress** — Story ID, phase, progress numbers
4. **Blocked** — Blocker description with error messages
5. **Risks** — Active risks, new risks, mitigations
6. **Next Step** — Exact command or decision
7. **Forbidden Actions** — Specific prohibitions
8. **Evidence Paths** — File paths for all artifacts
9. **Profile State** — Active profile, available profiles
10. **Need Human** — YES/NO with reasoning

## 8. Risk Register

| # | Risk | Likelihood | Impact | Mitigation |
|---|------|------------|--------|------------|
| R1 | DeepSeek Pro timeout on escalation | Medium | High | Reduce output to 4096, 3-bullet summary |
| R2 | Pro misused as builder | Medium | High | Profile policy enforced in config |
| R3 | GA Monitor auto-repairs | Low | Critical | Protocol: read-only mandate |
| R4 | Recursive D drive scan | Medium | High | Scan guard in runbook |
| R5 | Local model VRAM exhaustion | Medium | Medium | One model at a time |
| R6 | Evidence pack incomplete | High | Medium | Mandatory checklist per task |
| R7 | context-mode batch_execute stalls | Medium | Medium | Timeout limits, split large batches |
| R8 | Profile config drift | Low | High | Config diff in every evidence pack |
| R9 | Silent context exhaustion | Medium | High | ctx_stats periodic check |
| R10 | Handoff ambiguity | Medium | Medium | Strict template, mandatory sections |
| R11 | GA false positives on powershell | Low | Low | Process filter: exclude self-matches |
| R12 | Disk space exhaustion mid-run | Low | Critical | Pre-run check ≥ 100GB, monitor every 10min |

## 9. Next-Step Commands for GA

```powershell
# Check current status
Get-Content docs/longrun-control-plane/manifest.md | Select-String "current_phase|current_story|last_heartbeat"

# Run GREEN check
(Get-Volume D).SizeRemaining / 1GB
nvidia-smi --query-gpu=memory.free --format=csv,noheader
curl -s http://192.168.128.1:11434/v1/models

# Check for RED conditions
Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -match "DDownload|aidata|final_pack" } | Select-Object ProcessId, Name, CommandLine

# Write GA summary
# Output to: C:\Users\pc\.openclaw\reports\GA_MONITOR_SUMMARY_YYYY-MM-DD_HHmm.md
```

## 10. Next-Step Commands for OpenClaw (When Unfrozen)

```powershell
# Read manifest
Get-Content docs/longrun-control-plane/manifest.md

# Read latest handoff
Get-Content docs/longrun-control-plane/loops/latest-handoff.md

# Check RED status
Get-ChildItem docs/longrun-control-plane/reports/ -Filter "RED_*" | Sort-Object LastWriteTime -Descending | Select-Object -First 1

# Resume from checkpoint
# Read last checkpoint, verify environment, update manifest status=running
```
