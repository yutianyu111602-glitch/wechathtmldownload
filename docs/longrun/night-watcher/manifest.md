<!-- CODE_ALIGNMENT_2026_04_30_START -->
> Code alignment note (2026-04-30): this document was reviewed during the repository-wide docs/code sync. Treat `README.md`, `AGENTS.md`, `docs/CURRENT_CODE_MAP.md`, `docs/CLI_REFERENCE.md`, `docs/CONFIGURATION.md`, `docs/CODE_AUDIT.md`, and `docs/DOCUMENTATION_INDEX.md` as current code-aligned SSOT. Older dated handoffs/logs remain historical evidence and must be checked against current code before execution.
<!-- CODE_ALIGNMENT_2026_04_30_END -->

# Night Watcher Longrun Manifest — Resume Edition

**Generated:** 2026-04-26  
**Updated:** 2026-04-27 (Resume Edition)  
**Mode:** unattended (direct CLI execution)  
**Status:** running  
**Current Phase:** Phase 1 — final_pack  
**Current Story:** US-002  
**Iteration:** 2  

---

## Run State

```yaml
run_state:
  mode: unattended
  status: completed
  current_phase: Phase 6 — checkpoint_stop
  current_story_id: US-006
  iteration: 6
  max_iterations: 24
  failure_budget: 3
  last_heartbeat_at: 2026-04-27T17:50:00+08:00
  last_verified_at: 2026-04-27T17:50:00+08:00
  next_resume_cursor: "全部 story 通过，管线完成"
  stop_reason: "all_stories_passed"
  execution_method: direct_cli
  artifacts:
    prd: docs/longrun/night-watcher/prd.json
    prd_legacy: docs/longrun/night-watcher/04-prd.json
    execution_plan: docs/longrun/night-watcher/EXEC_PLAN_RESUME_2026-04-27.md
    full_prd: docs/longrun/night-watcher/PRD_NIGHT_WATCHER_RESUME_2026-04-27.md
    latest_handoff: HANDOFF_2026-04-27_NIGHT_WATCHER_COMPLETED.md
    legacy_handoff: HANDOFF_2026-04-27_NIGHT_WATCHER_RESUME.md (superseded, pre-execution)
    gateway: ws://127.0.0.1:18789 (live, but not used for execution)
```

---

## Story Status

| Story | Title | Priority | Status | Notes |
|-------|-------|----------|--------|-------|
| US-001 | 环境预检 | 1 | ✅ PASS | 实测通过 |
| US-002 | finalize-llm-pack | 2 | ✅ PASS | 93000 articles |
| US-003 | 输出验证 | 3 | ✅ PASS | 20/20 抽样通过 |
| US-004 | 参数校准 sweep | 4 | ✅ PASS | stable 最优 |
| US-005 | 下游评估矩阵 | 5 | ✅ PASS | 95% success |
| US-006 | checkpoint_stop | 6 | ✅ PASS | 报告已生成 |

---

## 系统基线（2026-04-27 实测）

| 资源 | 值 | 状态 |
|------|-----|------|
| GPU RTX 4090 | 17% util, 20GB VRAM free, 47°C | ✅ |
| 内存 | 25GB free / 64GB | ✅ |
| 磁盘 D: | 8,612 GB free / 14.9TB | ✅ |
| Qwen3.6-27B | llama-swap @ 11434 | ✅ |
| Stage Lock | 不存在 | ✅ |
| OpenClaw Gateway | ws://127.0.0.1:18789 live | ✅ (备用) |

---

## 数据清单

| 数据 | 路径 | 数量 | 状态 |
|------|------|------|------|
| Raw archives | D:/DDownload/_archive_mptext/ | 93,653 / 63 clubs | COMPLETE |
| LLM artifacts | D:/DDownload/_llm_artifacts/ | ~108K / 63 clubs | COMPLETE |
| MD mirror | D:/DDownload/_llm_md/ | 93,000 .md | COMPLETE |
| Release (partial) | D:/DDownload/_llm_release/ | 68,782 / 49 clubs | PARTIAL 73.7% |
| Release v2 | D:/DDownload/_llm_release_v2/ | — | NOT STARTED |

---

## 执行策略变更

**原计划 (v1-v2):** OpenClaw cron + agent 全自动  
**实际发现:** OpenClaw Gateway 存活但 cron 从未创建，agent 超时风险未知  
**新策略 (v3):** 直接 CLI 执行，agent 同步等待每步完成，验证后再下一步

优势：
- 不依赖 OpenClaw cron/agent 基础设施
- 同步执行，无超时不确定性
- 每步完成后立即验证

---

## 文档索引

| # | 文档 | 路径 |
|---|------|------|
| 0 | **本文件（SSOT）** | `docs/longrun/night-watcher/manifest.md` |
| 1 | prd.json (Ralph) | `docs/longrun/night-watcher/prd.json` |
| 2 | 完整 PRD | `docs/longrun/night-watcher/PRD_NIGHT_WATCHER_RESUME_2026-04-27.md` |
| 3 | 执行方案 v3 | `docs/longrun/night-watcher/EXEC_PLAN_RESUME_2026-04-27.md` |
| 4 | 接手报告 | `HANDOFF_2026-04-27_NIGHT_WATCHER_RESUME.md` |
| 5 | 旧 prd.json | `docs/longrun/night-watcher/04-prd.json` |
| 6 | 旧执行方案 | `docs/longrun/night-watcher/05-execution-plan.md` |

---

## Stop Gates

- 危险操作（删除/force/reset）
- 同一 story 失败 3 次
- 磁盘 < 5GB
- 模型不可用（3 次重试后）
- 24 次迭代上限
- 全部 story 通过

---

## Resume Rule

任何 agent 接手：
1. 读本文件
2. 读 prd.json 看 story 状态
3. 从第一个 `passes: false` 的 story 开始
4. 按 EXEC_PLAN_RESUME_2026-04-27.md 中的命令执行
5. 结果追加到 NIGHT_WATCHER_LOG_2026-04-27.md
