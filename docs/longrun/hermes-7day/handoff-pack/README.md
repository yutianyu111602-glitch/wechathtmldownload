<!-- CODE_ALIGNMENT_2026_04_30_START -->
> Code alignment note (2026-04-30): this document was reviewed during the repository-wide docs/code sync. Treat `README.md`, `AGENTS.md`, `docs/CURRENT_CODE_MAP.md`, `docs/CLI_REFERENCE.md`, `docs/CONFIGURATION.md`, `docs/CODE_AUDIT.md`, and `docs/DOCUMENTATION_INDEX.md` as current code-aligned SSOT. Older dated handoffs/logs remain historical evidence and must be checked against current code before execution.
<!-- CODE_ALIGNMENT_2026_04_30_END -->

# Hermes 7-Day WSL2 Super Longrun Handoff Pack

**Generated:** 2026-04-28
**Target:** Hermes Agent running in WSL2 with deepseek-v4-pro
**Duration:** 7+ days unattended-but-guarded
**Primary Goal:** Continuous WeChat article capture + downstream structured extraction

---

## One-Line Summary

Hermes in WSL2 orchestrates a 7-day continuous WeChat article capture pipeline using deepseek-v4-pro for planning and Qwen3.6-27B for local structured extraction, with mem0 cross-session memory, checkpoint/resume, and read-only monitoring.

---

## What This Pack Contains

| Category | Files | Purpose |
|----------|-------|---------|
| **Entry** | `README.md`, `START_HERE_FOR_HERMES.md` | Get started fast |
| **PRD** | `docs/01_PRD_HERMES_7DAY.md` | 15 user stories with acceptance criteria |
| **Ralph** | `prd/hermes-7day.prd.json` | Machine-executable story queue |
| **Execution** | `docs/02_EXECUTION_PLAN.md` | Day-by-day schedule with gates |
| **Operations** | `docs/03_RUNBOOK.md` | Commands, procedures, recovery |
| **Monitoring** | `docs/04_MONITOR_PROTOCOL.md` | Read-only GREEN/AMBER/RED rules |
| **Safety** | `docs/05_SAFETY_POLICY.md` | Hard bans, scan guards, failure budgets |
| **Config** | `docs/06_WSL2_HERMES_CONFIG.md` | WSL2-specific Hermes configuration |
| **Risk** | `docs/07_RISK_REGISTER.md` | Top 15 risks and mitigations |
| **Scripts** | `scripts/start-hermes-7day.sh` | Main startup and orchestration |
| **Templates** | `templates/*.md` | Checkpoint, handoff, RED report templates |

---

## Recommended Placement

Copy entire `handoff-pack/` directory to:

```bash
# WSL2 path
~/wechathtmldownload/docs/longrun/hermes-7day/handoff-pack
```

Or Windows path:
```powershell
C:\code\githubstar\wechathtmldownload\docs\longrun\hermes-7day\handoff-pack
```

---

## Quick Start

```bash
# 1. Enter WSL2
wsl

# 2. Navigate to pack
cd ~/wechathtmldownload/docs/longrun/hermes-7day/handoff-pack

# 3. Read startup instructions
cat START_HERE_FOR_HERMES.md

# 4. Run preflight
bash scripts/start-hermes-7day.sh preflight

# 5. If GREEN, start Day 0
bash scripts/start-hermes-7day.sh day0
```

---

## Core Principles

1. **Hermes in WSL2, Windows UI on host** — Hermes orchestrates from WSL2; Windows UI automation runs on Windows host via interop
2. **deepseek-v4-pro for planning, Qwen3.6-27B for execution** — Cloud model makes decisions, local model does structured extraction
3. **mem0 for cross-session memory** — Learnings persist across Hermes sessions
4. **Checkpoint every 30 min or 50 articles** — Never lose progress
5. **Read-only monitoring** — Hermes monitor observes, does not auto-fix
6. **Evidence before action** — Every story leaves traceable evidence

---

## Hard Rules

- Do NOT modify `D:\DDownload\_llm_release_v2`
- Do NOT recursive scan `D:\DDownload` or `D:\aidata`
- Do NOT delete any capture output without dry-run plan
- Do NOT start OpenClaw / AG as controller
- Do NOT use OpenRouter fallback
- Do NOT auto-kill WeChat or Windows processes
- Do NOT run `hermes` commands that steal mouse/keyboard without verification
- All cleanup must be dry-run first
- All long tasks must have checkpoint + run log

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────────┐
│                          WSL2 (Ubuntu)                                   │
│  ┌─────────────┐    ┌─────────────┐    ┌─────────────┐    ┌──────────┐  │
│  │   Hermes    │───→│ deepseek-v4 │───→│   mem0      │───→│  Local   │  │
│  │   Agent     │    │    -pro     │    │  Memory     │    │  Qwen    │  │
│  └──────┬──────┘    └─────────────┘    └─────────────┘    └──────────┘  │
│         │                                                                 │
│         │ WSL2 interop (wslpath, /mnt/d/)                                │
│         ▼                                                                 │
└─────────────────────────────────────────────────────────────────────────┘
         │
         │ Windows UI Automation
         ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                          Windows Host                                    │
│  ┌─────────────┐    ┌─────────────┐    ┌─────────────┐    ┌──────────┐  │
│  │  WeChat PC  │───→│ Hermes      │───→│   D:\HTML   │───→│ loopy-   │  │
│  │  Desktop    │    │  wechat     │    │  captures   │    │ archiver │  │
│  │  App        │    │  capture    │    │             │    │ pipeline │  │
│  └─────────────┘    └─────────────┘    └──────┬──────┘    └──────────┘  │
│                                                │                         │
│                                                ▼                         │
│                                        ┌─────────────┐                   │
│                                        │ D:\DDownload│                   │
│                                        │ _llm_release│                   │
│                                        │     _v2     │                   │
│                                        └─────────────┘                   │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## Contact & Recovery

If Hermes crashes or WSL2 shuts down:
1. Restart WSL2: `wsl --shutdown && wsl`
2. Resume from latest checkpoint: `bash scripts/start-hermes-7day.sh resume`
3. Check state: `cat state/run-state.json`
4. If RED, read latest `reports/RED_ANALYSIS_*.md`

---

**End of README. Read `START_HERE_FOR_HERMES.md` next.**
