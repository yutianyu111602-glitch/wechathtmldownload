# 研究档案总索引 — 2026-05-19

本目录为 **周活小程序接手包** 的只读档案库，汇总两轮深度研究 + P0 执行产物。  
权威编辑稿在上一级 `docs/weekly-miniprogram-handoff-20260519/*.md`；此处保留 **原始推理输出** 便于审计复现。

## 两轮研究关系（勿混淆）

| 轮次 | 名称 | 引擎 | 产出 | 用途 |
|------|------|------|------|------|
| **R1** | DeepSeek Prompt Matrix | `deepseek-v4-flash` / `pro` 在线 API + 评测脚本 | `deepseek_prompt_matrix_20260518/` | 生产模型策略：Flash 全量 + Pro 风险行；`yellowpage_gate_v3` |
| **R2a** | LDR 深度研究 · 计划一 | LDR + `deepseek-v4-pro` @ api.deepseek.com | `ldr_raw_20260519/weekly_plan_a_*` | 强化 → [PLAN_A_DEEPRESEARCH_v2.md](../PLAN_A_DEEPRESEARCH_v2.md) |
| **R2b** | LDR 深度研究 · 计划二 | 同上 | `ldr_raw_20260519/weekly_plan_b_*` | 强化 → [PLAN_B_DEEPRESEARCH_v2.md](../PLAN_B_DEEPRESEARCH_v2.md) |

R2 运行记录：[DEEPRESEARCH_RUN_20260519.md](../DEEPRESEARCH_RUN_20260519.md)

## 目录清单

### `ldr_raw_20260519/` — LDR 原始报告（含 JSON 推理元数据）

| 文件 | 说明 |
|------|------|
| `weekly_plan_a_deepseek_v4_pro_20260519.md` | 计划一候选全文；`model=deepseek-v4-pro`，`endpoint=https://api.deepseek.com` |
| `weekly_plan_b_deepseek_v4_pro_20260519.md` | 计划二候选全文 |

主副本仍保留：`C:\code\local-deep-research-wechat\data\research_outputs\`（本 archive 为接手包内镜像）。

### `ldr_source_pack_20260519/` — LDR 任务提示词

| 文件 | 说明 |
|------|------|
| `research_query_plan_a.md` | 发给 LDR 的计划一研究任务 |
| `research_query_plan_b.md` | 发给 LDR 的计划二研究任务 |

完整源包（10 份 MD）：`C:\code\local-deep-research-wechat\source_pack\weekly_plan_deepresearch_20260519\`

### `deepseek_prompt_matrix_20260518/` — R1 矩阵结论

| 文件 | 说明 |
|------|------|
| `weekly_deepseek_prompt_matrix_20260518_FINDINGS.md` | Flash/Pro × thinking × prompt 评测结论 |

### `p0_golden_20260519/` — P0 执行档案

| 文件 | 说明 |
|------|------|
| `golden_set_v1.jsonl` | 88 条金标种子（`annotation_status: pending`） |
| `golden_set_v1.manifest.json` | 引导 manifest |
| `golden_baseline_20260519.json` | 机器可读 baseline |
| `golden_baseline_20260519.md` | 人类可读 baseline（与 [P0_BASELINE_REPORT](../P0_BASELINE_REPORT_20260519.md) 同内容） |

工作副本：`D:\downstream_results\golden\`（与 archive 内 jsonl 同步于 2026-05-19 引导时）。

## 接手包内精炼稿（非 archive，为 SSOT 阅读入口）

| 层级 | 文件 |
|------|------|
| v1 概要 | `PLAN_A_WEEKLY_*.md`, `PLAN_B_WEEKLY_*.md` |
| **v2 实施稿** | `PLAN_A_DEEPRESEARCH_v2.md`, `PLAN_B_DEEPRESEARCH_v2.md` |
| L0 契约 | `WeeklyAtlasEntityContract.md` |
| P0 状态 | `P0_EXECUTION_STATUS_20260519.md`, `P0_BASELINE_REPORT_20260519.md` |
| 主接手 | `NEXT_AGENT_HANDOFF_WEEKLY_MINIPROGRAM_FULL.md` |

## 状态门

| 档案类型 | `confirmed_truth` | 下一门 |
|----------|-------------------|--------|
| LDR R2 原始报告 | **false**（候选研究） | HOLD_FOR_HERMES_DECISION |
| v2 精炼稿 | **false**（设计稿） | 用户批准 → P0/P1 实施 |
| P0 golden/baseline | **事实快照**（可复现） | 待人工 verified |

## 复现 LDR R2

见 [DEEPRESEARCH_RUN_20260519.md](../DEEPRESEARCH_RUN_20260519.md) 内 `docker exec ldr-wechat-research ...` 命令。
