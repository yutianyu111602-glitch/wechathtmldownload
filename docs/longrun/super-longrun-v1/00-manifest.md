<!-- CODE_ALIGNMENT_2026_04_30_START -->
> Code alignment note (2026-04-30): this document was reviewed during the repository-wide docs/code sync. Treat `README.md`, `AGENTS.md`, `docs/CURRENT_CODE_MAP.md`, `docs/CLI_REFERENCE.md`, `docs/CONFIGURATION.md`, `docs/CODE_AUDIT.md`, and `docs/DOCUMENTATION_INDEX.md` as current code-aligned SSOT. Older dated handoffs/logs remain historical evidence and must be checked against current code before execution.
<!-- CODE_ALIGNMENT_2026_04_30_END -->

# 00-manifest.md — Super Long Run v1 Entry

**Created:** 2026-04-27
**Status:** COMPLETE
**Profile:** deepseek_builder
**Purpose:** Single entry point for the super-longrun-v1 plan. All other files hang off this one.

> NOTE: This file is the numbered entry (00). `manifest.md` is the main working manifest with full run_state.

---

## 当前事实

| Fact | Value |
|------|-------|
| LLM Release Pack | 93,000 articles, D:/DDownload/_llm_release_v2/ |
| LLM Artifacts | ~108K, D:/DDownload/_llm_artifacts/ |
| LLM MD Mirror | ~108K, D:/DDownload/_llm_md/ |
| Rawwechat HTML | 8,095, D:/rawwechat/ |
| Rawwechat MD | 8,095 (100%), D:/rawwechat_md/ |
| D drive free | 8,612 GB |
| Local model | Qwen3.6-27B @ llama-swap:11434 |
| OpenCode model | DeepSeek V4 Pro (deepseek_builder) |
| Clubs | 63 |
| Working dir | C:\code\githubstar\wechathtmldownload |

---

## 非目标

- Not: 递归扫描 D:\DDownload / D:\aidata
- Not: 启动 OpenClaw / AG / Hermes 作为主控
- Not: 删除 lock 文件或自动修复业务任务
- Not: 写入生产库
- Not: 重跑 Stage 0-6
- Not: 使用 OpenRouter
- Not: 引入 Mac M3 Pro / 向量模型

---

## 输入

- `GLOBAL_DATA_INVENTORY.md` — 数据口径
- Existing `manifest.md` — 旧版计划
- Existing `03-prd.md` — 旧版 PRD (274 lines, restructured into 01-PRD.md + 07-story-map.md)
- Existing `05-execution-plan.md` — 旧版执行计划

---

## 输出 (本骨架写入的文件)

| # | File | Purpose | Status |
|---|------|---------|--------|
| 00 | `00-manifest.md` | Entry, inventory, role map, bans | COMPLETE |
| 01 | `01-PRD.md` | Full PRD with 13 User Stories | COMPLETE |
| 02 | `02-execution-plan.md` | Execution order, deps, per-US CLI commands | COMPLETE |
| 03 | `03-operations-manual.md` | How to operate, gates, health checks, recovery | COMPLETE |
| 04 | `04-ga-monitor-spec.md` | GA read-only monitor spec (9 checks) | COMPLETE |
| 05 | `05-safety-policy.md` | Safety rules (12 guards), bans, stop gates | COMPLETE |
| 06 | `06-context-gate-policy.md` | Context gate policy (3 thresholds, 5 queues) | COMPLETE |
| 07 | `07-story-map.md` | 13 stories: full dependency graph + timeline | COMPLETE |
| 08 | `08-runbook.md` | Step-by-step PowerShell runbook | COMPLETE |
| 09 | `09-handoff-template.md` | Handoff template for loops | COMPLETE |

### Additional Files
| Path | Purpose | Status |
|------|---------|--------|
| `templates/*` | 5 templates (checkpoint, final-report, handoff, error-taxonomy, progress) | COMPLETE |
| `baseline/README.md` | Baseline directory docs | COMPLETE |
| `reports/README.md` | Report file descriptions | COMPLETE |
| `tools/super-longrun/*` | 4 PS1 skeleton scripts + README | COMPLETE |
| `loops/loop-001-handoff.md` | AI-to-AI handoff report | COMPLETE |
| `manifest.md` | Main working manifest with full run_state | COMPLETE |

---

## Profile & Model Config

### Active Profiles

```
deepseek_builder (DEFAULT for this plan)
  provider: deepseek official direct
  model: deepseek-v4-pro
  max_tokens: 4096
  temperature: 0.2
  timeout: 180s
  retries: 2
  stream: true
  use: PRD, execution plan, story map, runbook, skeleton writes

deepseek_escalation (ON-DEMAND only)
  provider: deepseek official direct
  model: deepseek-v4-pro
  max_tokens: 8192
  temperature: 0.2
  timeout: 300s
  retries: 1
  use: complex anomaly analysis, RED root-cause, long-context review
  DO NOT use: file writes, skeleton generation

deepseek_watch (MONITORING only)
  provider: deepseek official direct
  model: deepseek-v4-flash
  max_tokens: 2048
  temperature: 0.1
  timeout: 90s
  retries: 2
  use: read-only monitoring, checkpoint summaries
```

---

## Write Strategy (Hard Rule)

1. One file at a time. No parallel writes.
2. Skeleton first (120-180 lines). Expand later.
3. Each write/edit/append ≤ 180 lines.
4. PRD (01-PRD.md) = goals + phases only. Story details → 07-story-map.md.
5. If write timeout → stop immediately, use smaller append. Don't retry same chunk.

---

## Role Map

| Role | Responsibility | Write? |
|------|---------------|--------|
| Qwen3.6-27B (local) | Planning, docs, decisions | Read-only analysis + doc output |
| DeepSeek V4 Pro (deepseek_builder) | File writes, skeleton generation | Yes (≤180 lines per write) |
| GA Agent | Read-only monitoring, disk check, alerts | No |
| OpenCode | Execute explicit commands only | Per instruction |
| OpenClaw | FROZEN | FROZEN |
| AG | FROZEN | FROZEN |
| Hermes | Not used this phase | FROZEN |

---

## Stop Gates

Stop entire run if ANY of:
- [ ] Write tool timeout 2x consecutively
- [ ] D: free space < 100 GB
- [ ] LLM service (llama-swap) unreachable > 3 retries
- [ ] Any file corruption detected
- [ ] Human issues STOP command

---

## Run State

```yaml
run: super-longrun-v1
phase: SKELETON_COMPLETE
status: complete
current_phase: Phase 0 (Pre-Flight)
current_story_id: US-000
loop: 1
max_loops: 24
failure_budget: 3
last_heartbeat: 2026-04-27T19:35:00+08:00
model: deepseek_builder (deepseek-v4-pro)
write_strategy: skeleton-first, one-file-at-a-time, max-180-lines
next_resume_cursor: US-000
stop_reason: "Skeleton build complete. Awaiting human review."
production_task_started: false
openclaw_started: false
final_pack_started: false
```

---

## Phases (High-Level)

| Phase | Story | Description |
|-------|-------|-------------|
| 0 | US-000 | Tooling Capability Audit (PRE-FLIGHT) |
| 1 | US-001 | Baseline Freeze |
| 2 | US-001B | Context Gate & Long Article Policy |
| 3 | US-002 | Downstream Dry-run 100 (Ready-only) |
| 4 | US-003 | Downstream Smoke 1000 (Ready-only) |
| 5 | US-004 | Full Ready Subset Downstream Batch |
| 6 | US-005 | Review / Blocked Queue Report |
| 7 | US-006 | Downstream Quality Report |
| 8 | US-007 | Graph Candidate Pack Dry-run |
| 9 | US-008 | Rawwechat Legacy Verification & Archive |
| 10 | US-009 | Safety Policy Hardening |
| 11 | US-010 | GA Monitor Integration |
| 12 | US-011 | Cleanup Dry-run Plan |
| 13 | US-012 | Final Report and Handoff |

Total: 14 Phases, 13 User Stories

---

## Dependency Graph

```
US-000 (Tooling Audit) ─────────────────────────────────┐
  ↓                                                      │
US-001 (Baseline Freeze) ────────────────────────────────┤
  ↓                                                      │
US-001B (Context Gate) ──────────────────────────────────┤
  ↓                                                      │
US-002 (Dry-run 100) ─── US-008 (Rawwechat Verify) ─────┤
  ↓                         (parallel)                   │
US-003 (Smoke 1000) ────── US-009 (Safety Audit) ───────┤
  ↓                         (parallel)                   │
US-004 (Full Batch) ────── US-010 (GA Monitor) ─────────┤
  ↓                         (parallel)                   │
US-005 (Review Report) ─── US-011 (Cleanup Plan) ───────┤
  ↓                         (parallel)                   │
US-006 (Quality Report)                                   │
  ↓                                                       │
US-007 (Graph Candidate)                                  │
  ↓                                                       │
US-012 (Final Handoff) ←─────────────────────────────────┘
```

---

## Hard Bans (Repeated — MUST NOT)

1. NO recursive scan D:\DDownload, D:\aidata, /mnt/d/*
2. NO auto-deleting lock files
3. NO auto-write to production DB
4. NO starting OpenClaw, AG, Hermes as controller
5. NO re-running Stage 0-6
6. NO OpenRouter
7. NO Escalation profile for file writes
8. NO parallel file writes
9. NO single write > 180 lines
10. NO retrying timed-out write with same payload

---

## TODO

- [x] Expand skeleton -> full content
- [x] Create loops/ directory
- [x] Create archive/ directory
- [x] Create baseline/ directory
- [x] Create templates/ directory
- [x] Create tools/super-longrun/ with 5 scripts
- [x] Verify all files exist (26 files in super-longrun-v1/)
- [x] Write AI-to-AI handoff (loop-001-handoff.md)
- [ ] Human approves -> begin Phase 0 execution (US-000)
