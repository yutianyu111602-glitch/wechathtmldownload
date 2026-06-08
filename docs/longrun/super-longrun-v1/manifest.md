<!-- CODE_ALIGNMENT_2026_04_30_START -->
> Code alignment note (2026-04-30): this document was reviewed during the repository-wide docs/code sync. Treat `README.md`, `AGENTS.md`, `docs/CURRENT_CODE_MAP.md`, `docs/CLI_REFERENCE.md`, `docs/CONFIGURATION.md`, `docs/CODE_AUDIT.md`, and `docs/DOCUMENTATION_INDEX.md` as current code-aligned SSOT. Older dated handoffs/logs remain historical evidence and must be checked against current code before execution.
<!-- CODE_ALIGNMENT_2026_04_30_END -->

# Super Long Run Plan v1 — Manifest (Unified)

**Created:** 2026-04-27
**Updated:** 2026-04-27 19:30
**Status:** SKELETON COMPLETE (awaiting human review)
**Parent:** `docs/longrun/`

---

## File Index

### Core Documents (Numbered)
| File | Description | Status |
|------|-------------|--------|
| `manifest.md` | This file (single entry point) | ✅ Current |
| `01-PRD.md` | Full PRD with 13 User Stories | ✅ New |
| `02-execution-plan.md` | Detailed execution plan with CLI commands | ✅ New |
| `03-operations-manual.md` | Operations manual (pre-start, gates, recovery) | ✅ New |
| `04-ga-monitor-spec.md` | GA read-only monitor specification | ✅ New |
| `05-safety-policy.md` | Safety policy (12 guard rules) | ✅ New |
| `06-context-gate-policy.md` | Context Gate design and queue policy | ✅ New |
| `07-story-map.md` | Story dependency graph and timeline | ✅ New |
| `08-runbook.md` | Step-by-step execution guide | ✅ New |
| `09-handoff-template.md` | Handoff template for loop handoffs | ✅ New |

### Supporting Documents
| File | Description | Status |
|------|-------------|--------|
| `02-board-discussion.md` | Board Discussion records (3 rounds) | ✅ |
| `03-prd.md` | PRD v0.1 (superseded by 01-PRD.md) | ⚠️ Superseded |
| `04-prd.json` | Ralph PRD JSON | ✅ |
| `05-execution-plan.md` | Execution Plan v0.1 (superseded by 02-execution-plan.md) | ⚠️ Superseded |
| `01-super-longrun-plan-v1.md` | Old plan (reference only) | ⚠️ Superseded |
| `GLOBAL_DATA_INVENTORY.md` | Global data inventory (unified) | ✅ |

### Directories
| Dir | Description | Status |
|-----|-------------|--------|
| `templates/` | Checkpoint, report, handoff, error, progress templates | ✅ Created |
| `baseline/` | Baseline snapshot directory | ✅ Created |
| `reports/` | Report output directory | ✅ Created |
| `loops/` | Loop handoff directory | ✅ Created |
| `archive/` | Historical archive directory | ✅ Created |
| `queues/` | Context Gate queue output | 📁 Created at runtime |

### Scripts
| Script | Description | Status |
|--------|-------------|--------|
| `tools/super-longrun/collect-tooling-capability.ps1` | US-000 audit script | ✅ Skeleton |
| `tools/super-longrun/collect-baseline-metadata.ps1` | US-001 baseline script | ✅ Skeleton |
| `tools/super-longrun/context-gate-plan.ps1` | US-001B gate script | ✅ Skeleton |
| `tools/super-longrun/validate-no-dangerous-scan.ps1` | Pre-flight safety check | ✅ Skeleton |
| `tools/super-longrun/run-dryrun-100-skeleton.ps1` | US-002 pre-flight path validator | ✅ Skeleton |

---

## 计划概要

### Phase 0-5: 下游抽取与图谱
- **Phase 0:** Baseline Freeze — 冻结产物快照
- **Phase 1:** Downstream Dry-run 100 — 100 篇验证
- **Phase 2:** Downstream Smoke 1000 — 1000 篇压力测试
- **Phase 3:** Full 93K Downstream Batch — 全量结构化抽取
- **Phase 4:** Downstream Quality Report — 质量统计
- **Phase 5:** Graph Candidate Pack — 图谱候选生成

### Phase 6-8: 清理与基线
- **Phase 6:** Temp Files Cleanup — 清理 27 个 tmp-* 目录和临时文件
- **Phase 7:** Documentation Consolidation — 归档过期文档, 统一口径
- **Phase 8:** Code Quality Baseline — 记录技术债, 不修改代码

### Phase 9-10: 监控与收口
- **Phase 9:** GA Monitor Integration — 只读监控集成
- **Phase 10:** Final Report and Handoff — 最终报告

---

## User Stories (11 个)

| ID | Title | Priority | Status |
|----|-------|----------|--------|
| US-001 | Baseline Freeze | 1 | ⏳ Ready |
| US-002 | Downstream Dry-run 100 | 2 | ⏳ Ready |
| US-003 | Downstream Smoke 1000 | 3 | ⏳ Ready |
| US-004 | Full 93K Downstream Batch | 4 | ⏳ Ready |
| US-005 | Quality Report | 5 | ⏳ Ready |
| US-006 | Graph Candidate Pack | 6 | ⏳ Ready |
| US-007 | Temp Files Cleanup | 7 | ⏳ Ready |
| US-008 | Documentation Consolidation | 8 | ⏳ Ready |
| US-009 | Code Quality Baseline | 9 | ⏳ Ready |
| US-010 | GA Monitor Integration | 10 | ⏳ Ready |
| US-011 | Final Report and Handoff | 11 | ⏳ Ready |

---

## 全局数据清单 (统一口径)

| 数据项 | 值 | 来源 | 更新时间 |
|--------|-----|------|----------|
| LLM Release Pack | 93,000 篇 | D:/DDownload/_llm_release_v2/ | 2026-04-27 |
| LLM Artifacts | ~108K | D:/DDownload/_llm_artifacts/ | 2026-04-27 |
| LLM MD Mirror | ~108K | D:/DDownload/_llm_md/ | 2026-04-27 |
| Clubs | 63 | manifest.json | 2026-04-27 |
| Rawwechat HTML | 8,095 | D:/rawwechat/ | 2026-04-27 |
| Rawwechat MD | 8,095 (100%) | D:/rawwechat_md/ | 2026-04-27 |
| D 盘剩余空间 | 8,612 GB | Get-Volume D | 2026-04-27 |
| 模型 | Qwen3.6-27B | llama-swap:11434 | 2026-04-27 |
| 校准参数 | temp=0.1, top_p=0.9, max=2048 | qwen3.6-calibration/ | 2026-04-27 |
| 下游评估 | 60 evals, 95% success | tmp-downstream-eval/ | 2026-04-27 |

---

## 硬性禁令

1. ❌ 不递归扫描 D:\DDownload / D:\aidata / /mnt/d/*
2. ❌ 不自动删除 lock / 自动修复业务任务
3. ❌ 不自动写入生产库
4. ❌ 不启动 OpenClaw / AG / Hermes 作为主控
5. ❌ 不重跑 Stage 0-6
6. ❌ 不引入 Mac M3 Pro / 向量模型

---

## 角色分工

| 角色 | 职责 | 权限 |
|------|------|------|
| **Qwen3.6-27B** | 规划、文档、决策 | 只读分析 + 文档输出 |
| **GA Agent** | 只读监控、checkpoint 检查、D 盘安全、告警摘要 | 只读，禁止写/删/杀进程 |
| **OpenCode** | 后续执行器，仅执行明确命令 | 按指令执行，不自主决策 |
| **OpenClaw** | 冻结 | 不作为主控 |
| **AG** | 冻结 | 不作为主控 |
| **Hermes** | 本阶段不用 | 冻结 |

---

## 运行状态

```yaml
run_state:
  mode: unattended
  status: skeleton_complete
  current_phase: Phase 0 (Pre-Flight)
  current_story_id: US-000
  iteration: 0
  max_iterations: 24
  failure_budget: 3
  last_heartbeat_at: 2026-04-27T19:35:00+08:00
  last_verified_at: 2026-04-27T19:35:00+08:00
  next_resume_cursor: US-000
  stop_reason: "Skeleton build complete. Awaiting human review."
  skeleton_ready: true
  artifacts:
    prd: docs/longrun/super-longrun-v1/01-PRD.md
    execution_plan: docs/longrun/super-longrun-v1/02-execution-plan.md
    operations_manual: docs/longrun/super-longrun-v1/03-operations-manual.md
    ga_monitor_spec: docs/longrun/super-longrun-v1/04-ga-monitor-spec.md
    safety_policy: docs/longrun/super-longrun-v1/05-safety-policy.md
    context_gate_policy: docs/longrun/super-longrun-v1/06-context-gate-policy.md
    prd_json: docs/longrun/super-longrun-v1/04-prd.json
    latest_handoff: loops/loop-001-handoff.md
    latest_scorecard: ""
    session_archive: ""
    crystallization_candidates: ""
```

---

## 依赖关系

```
US-001 (Baseline)
  ↓
US-002 (Dry-run 100)
  ↓
US-003 (Smoke 1000)
  ↓
US-004 (Full 93K)
  ↓
US-005 (Quality Report)
  ↓
US-006 (Graph Candidate)

US-007 (Temp Cleanup) — 独立, 可随时执行
US-008 (Doc Consolidation) — 独立, 可随时执行
US-009 (Code Baseline) — 独立, 可随时执行
US-010 (GA Monitor) — 独立, 可随时执行

US-011 (Final Report) — 依赖 US-001 ~ US-010
```

---

## 技术债 (记录但不修改)

| 问题 | 位置 | 影响 | 优先级 |
|------|------|------|--------|
| cli.ts 过长 (1215行) | src/cli.ts | 可维护性 | P2 |
| 类型重复 (BatchSnapshot vs ArchiveBatchSnapshot) | src/pipeline/, src/archive/ | 可维护性 | P3 |
| 硬编码路径 | src/desktop/runtimeImport.ts, npm scripts | 可移植性 | P2 |
| 错误处理不一致 | 多个文件 | 可靠性 | P2 |
| 工具函数重复定义 (toStringValue, toNumberValue, nowIso) | 多个文件 | 可维护性 | P3 |

---

## Next Steps

1. ~~Human review~~ → Skeleton complete
2. Review skeleton documents (01-09 + templates + scripts)
3. On approval: run US-000 (Tooling Capability Audit)
4. Continue through US-001 → US-012 per dependency chain

---

## History

| Version | Date | Description |
|---------|------|-------------|
| DRAFT v1 | 2026-04-27 | Initial (Qwen3.6 generated) |
| DRAFT v1 (user echo) | 2026-04-27 | User echo version (removed) |
| UNIFIED v1 | 2026-04-27 | Unified after Board Discussion |
| **SKELETON v1** | **2026-04-27** | **Full skeleton: 9 docs + 5 templates + 4 scripts** |
