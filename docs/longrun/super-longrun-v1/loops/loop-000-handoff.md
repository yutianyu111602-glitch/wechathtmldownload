<!-- CODE_ALIGNMENT_2026_04_30_START -->
> Code alignment note (2026-04-30): this document was reviewed during the repository-wide docs/code sync. Treat `README.md`, `AGENTS.md`, `docs/CURRENT_CODE_MAP.md`, `docs/CLI_REFERENCE.md`, `docs/CONFIGURATION.md`, `docs/CODE_AUDIT.md`, and `docs/DOCUMENTATION_INDEX.md` as current code-aligned SSOT. Older dated handoffs/logs remain historical evidence and must be checked against current code before execution.
<!-- CODE_ALIGNMENT_2026_04_30_END -->

# Loop Handoff — 规划完成 (统一口径版)

**Loop ID:** loop-000  
**日期:** 2026-04-27 18:51  
**状态:** ✅ 规划完成, 等待执行

---

## 本轮完成的工作

### 1. 蜂群扫描 (6 个 subagent)
- ✅ 新管线代码分析 (87+ 文件, Stage 0-6 完整流程)
- ✅ 旧管线代码分析 (三代管线, 临时文件泛滥)
- ✅ 计划文档分析 (5 个 longrun 计划, 口径不一致)
- ✅ 产物状态分析 (93K release pack, ~108K artifacts)
- ✅ Tools 脚本分析 (29 个脚本, 8 类功能)
- ✅ Rawwechat 状态分析 (8095/8095, 100% 完成)

### 2. Board Discussion (3 轮)
- ✅ Round 1: Facts (事实) — 6 个维度的完整事实
- ✅ Round 2: Conflicts (冲突) — Phase 6 冲突, 文档冗余, 数据口径
- ✅ Round 3: Decisions (决策) — Phase 6 重新定义, 新增 Phase 8, 统一规则

### 3. PRD 生成
- ✅ 03-prd.md (统一口径版 PRD)
- ✅ 04-prd.json (Ralph 格式, 11 stories)
- ✅ 05-execution-plan.md (执行计划)

### 4. 文档更新
- ✅ manifest.md (统一口径版, 含 run_state)
- ✅ GLOBAL_DATA_INVENTORY.md (全局数据清单)
- ✅ TECH_DEBT.md (技术债基线, 20 项)
- ✅ 02-board-discussion.md (Board 讨论记录)

### 5. 目录结构
- ✅ loops/ (loop handoff 目录)
- ✅ archive/ (历史归档目录)
- ✅ baseline/ (baseline 快照目录)

---

## 关键决策

### 决策 1: Phase 6 重新定义
- **原 Phase 6:** Rawwechat Legacy Repair (8095 篇恢复)
- **新 Phase 6:** Temp Files Cleanup & Documentation Consolidation
- **理由:** rawwechat 已 100% 完成, 无需修复

### 决策 2: 新增 Phase 8
- **Phase 8:** Code Quality Baseline
- **内容:** 记录技术债, 不修改代码
- **输出:** TECH_DEBT.md

### 决策 3: 文档统一规则
- manifest.md 为每个计划的唯一入口
- prd.json 统一放在 longrun 子目录内
- 历史文档移到 archive/ 子目录
- 重复文档合并或删除

### 决策 4: 清理优先级
- P0: 27 个 tmp-* 目录 + 根目录临时文件
- P1: 过期 HANDOFF 文件 + 废弃 docs/superpowers 文档
- P2: Mac 脚本 + DOUBAO 模板 + gpt-image-2 产物
- P3: genericagent-chinese/ + rawwechat package.json 脚本

### 决策 5: 管线运行方式
- 直接 CLI 执行 (不依赖 OpenClaw cron)
- 前台 PowerShell (不 Start-Process 包装)
- 可见日志输出 (可随时 Ctrl+C 中断)
- checkpoint 持久化 (支持中断恢复)
- failure_budget=3 (同一 story 最多修复 3 次)
- 每 3 个 story 一次 major checkpoint

---

## 数据口径统一

| 数据项 | 统一值 | 来源 |
|--------|--------|------|
| LLM Release Pack | 93,000 篇 | D:/DDownload/_llm_release_v2/ |
| LLM Artifacts | ~108K | D:/DDownload/_llm_artifacts/ |
| Clubs | 63 | manifest.json |
| Rawwechat HTML | 8,095 | D:/rawwechat/ |
| Rawwechat MD | 8,095 (100%) | D:/rawwechat_md/ |
| D 盘剩余空间 | 8,612 GB | Get-Volume D |
| 模型 | Qwen3.6-27B | llama-swap:11434 |
| 校准参数 | temp=0.1, top_p=0.9, max=2048 | qwen3.6-calibration/ |
| 下游评估 | 60 evals, 95% success | tmp-downstream-eval/ |

---

## 技术债基线

- **总数:** 20 项
- **P0:** 1 项 (tmp-* 清理)
- **P1:** 2 项 (API Key 默认值, HANDOFF 归档)
- **P2:** 8 项 (架构、安全、可观测性)
- **P3:** 9 项 (代码质量、测试、清理)
- **估计总工作量:** 17-21 天

---

## 下一步

1. **等待人工审核** 本计划 (manifest.md, 03-prd.md, 04-prd.json, 05-execution-plan.md)
2. **审核通过后,** 进入 US-001 (Baseline Freeze)
3. **按依赖顺序执行** US-001 ~ US-011
4. **每 3 个 story** 一次 major checkpoint
5. **达到 stop gate** 立即停止并 handoff

---

## 恢复入口

新 agent 可从以下文件恢复:
1. `docs/longrun/super-longrun-v1/manifest.md` — 唯一入口
2. `docs/longrun/super-longrun-v1/loops/loop-000-handoff.md` — 本文件
3. `docs/longrun/super-longrun-v1/04-prd.json` — Ralph PRD
4. `docs/longrun/super-longrun-v1/05-execution-plan.md` — 执行计划
5. `docs/longrun/super-longrun-v1/GLOBAL_DATA_INVENTORY.md` — 全局数据清单

---

## run_state 更新

```yaml
run_state:
  mode: unattended
  status: ready
  current_phase: Phase 0
  current_story_id: US-001
  iteration: 0
  max_iterations: 24
  failure_budget: 3
  last_heartbeat_at: 2026-04-27T18:51:00+08:00
  last_verified_at: 2026-04-27T18:51:00+08:00
  next_resume_cursor: US-001
  stop_reason: ""
  artifacts:
    prd: docs/longrun/super-longrun-v1/03-prd.md
    prd_json: docs/longrun/super-longrun-v1/04-prd.json
    latest_handoff: docs/longrun/super-longrun-v1/loops/loop-000-handoff.md
    latest_scorecard: ""
    session_archive: ""
    crystallization_candidates: ""
```
