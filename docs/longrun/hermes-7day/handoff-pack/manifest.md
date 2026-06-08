<!-- CODE_ALIGNMENT_2026_04_30_START -->
> Code alignment note (2026-04-30): this document was reviewed during the repository-wide docs/code sync. Treat `README.md`, `AGENTS.md`, `docs/CURRENT_CODE_MAP.md`, `docs/CLI_REFERENCE.md`, `docs/CONFIGURATION.md`, `docs/CODE_AUDIT.md`, and `docs/DOCUMENTATION_INDEX.md` as current code-aligned SSOT. Older dated handoffs/logs remain historical evidence and must be checked against current code before execution.
<!-- CODE_ALIGNMENT_2026_04_30_END -->

# Hermes 7-Day WSL2 Super Longrun — Manifest

**Created:** 2026-04-28
**Status:** READY_FOR_REVIEW
**Executor:** Hermes (WSL2) + deepseek-v4-pro
**Target:** WeChat article pipeline continuous capture + downstream processing
**Duration:** 7 days minimum (2026-04-28 to 2026-05-05)
**Workspace:** `C:\code\githubstar\wechathtmldownload`
**Hermes Repo:** `C:\code\Hermes`
**Output Base:** `D:\HTML\hermes-longrun-2026-04-28`

---

## Entry Points (Read in order)

1. `README.md` — Package overview
2. `START_HERE_FOR_HERMES.md` — Hermes-specific startup instructions
3. `docs/01_PRD_HERMES_7DAY.md` — Full PRD with 15 user stories
4. `prd/hermes-7day.prd.json` — Ralph executable story queue
5. `docs/02_EXECUTION_PLAN.md` — Day-by-day execution schedule
6. `docs/03_RUNBOOK.md` — Operations manual
7. `docs/04_MONITOR_PROTOCOL.md` — Read-only monitoring rules
8. `docs/05_SAFETY_POLICY.md` — Safety guards and hard bans
9. `docs/06_WSL2_HERMES_CONFIG.md` — WSL2-specific configuration
10. `docs/07_RISK_REGISTER.md` — Known risks and mitigations
11. `config/hermes.config.yaml` — Hermes runtime configuration
12. `scripts/start-hermes-7day.sh` — Main startup script

---

## Current Facts

| Item | Value |
|------|-------|
| Hermes version | Latest (C:\code\Hermes) |
| Hermes platform | WSL2 (Ubuntu) |
| LLM Provider | deepseek-v4-pro |
| WeChat capture | Windows UI automation via `tools.windows_wechat_history` |
| Existing release | `D:\DDownload\_llm_release_v2` — 93,000 articles |
| Existing models | Qwen3.6-27B (active), Qwen3.6-35B-A3B, Gemma-4-31B |
| D drive free | ~8.5 TB |
| C drive free | ~284 GB |
| GPU | RTX 4090, llama-swap:11434 |
| mem0 endpoint | http://127.0.0.1:11434/v1 (qwen3.5:4b) |

---

## Phase Map

| Phase | Name | Stories | Status |
|-------|------|---------|--------|
| P0 | WSL2 Hermes Setup & Preflight | US-000 ~ US-001 | NOT_STARTED |
| P1 | Baseline Freeze & Context Gate | US-002 ~ US-003 | NOT_STARTED |
| P2 | WeChat Capture Dry-run | US-004 ~ US-005 | NOT_STARTED |
| P3 | WeChat Capture Smoke & Resume | US-006 ~ US-007 | NOT_STARTED |
| P4 | Full WeChat Capture Batch | US-008 ~ US-010 | NOT_STARTED |
| P5 | Downstream LLM Processing | US-011 ~ US-012 | NOT_STARTED |
| P6 | Quality Report & Graph Candidate | US-013 ~ US-014 | NOT_STARTED |
| P7 | Final Handoff & Cleanup Plan | US-015 | NOT_STARTED |

---

## Model Profile Map

| Profile | Model | Role | Context |
|---------|-------|------|---------|
| hermes-builder | deepseek-v4-pro | PRD, planning, docs, config | Hermes WSL2 session |
| hermes-executor | deepseek-v4-pro | Task execution, file ops, scripts | Hermes WSL2 session |
| hermes-monitor | deepseek-v4-flash | Read-only monitoring, summaries | Cross-session |
| local-qwen | Qwen3.6-27B | Structured extraction, analysis | llama-swap:11434 |

---

## Stop Conditions

- GPU OOM or model unreachable 3x
- D drive I/O spike > 80% sustained
- Disk free < 50GB
- Hermes crash or WSL2 shutdown
- WeChat window not accessible
- Same story fails 3x in a row
- Dangerous scan process detected
- final_pack or OpenClaw auto-started

---

## Hard Bans

- Do NOT recursive scan `D:\DDownload`, `D:\aidata`
- Do NOT modify `D:\DDownload\_llm_release_v2`
- Do NOT delete any data, logs, lock files
- Do NOT start OpenClaw / AG as main controller
- Do NOT use OpenRouter fallback without explicit approval
- Do NOT auto-fix failed business tasks
- Do NOT run Hermes commands that require Windows UI without verification
- Do NOT commit/push to git automatically

---

## Next Action

1. Review this manifest
2. Read `START_HERE_FOR_HERMES.md`
3. Run preflight: `bash scripts/start-hermes-7day.sh preflight`
