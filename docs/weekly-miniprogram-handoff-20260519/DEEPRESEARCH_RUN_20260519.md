# 深度研究运行记录 — 2026-05-19

## 目的

在 `PLAN_A` / `PLAN_B` v1 设计稿基础上，使用本机 **local-deep-research-wechat** + **DeepSeek `deepseek-v4-pro`** 在线推理，产出可落地、可验收的强化版 v2 计划。

## 推理证据（LDR 合规）

| 项 | Plan A | Plan B |
|----|--------|--------|
| 模型 | `deepseek-v4-pro` | `deepseek-v4-pro` |
| 端点 | `https://api.deepseek.com` | 同左 |
| 容器 | `ldr-wechat-research` | 同左 |
| 策略 | `direct` | `direct` |
| 状态 | `confirmed_truth: false` | 同左 |
| 下一门 | `HOLD_FOR_HERMES_DECISION` | 同左 |

原始报告（含 JSON 元数据）：

- `C:\code\local-deep-research-wechat\data\research_outputs\weekly_plan_a_deepseek_v4_pro_20260519.md`
- `C:\code\local-deep-research-wechat\data\research_outputs\weekly_plan_b_deepseek_v4_pro_20260519.md`

## 源包

目录：`C:\code\local-deep-research-wechat\source_pack\weekly_plan_deepresearch_20260519\`

| 文件 | 来源 |
|------|------|
| `01_PLAN_A_*.md` | handoff PLAN_A |
| `02_PLAN_B_*.md` | handoff PLAN_B |
| `03_NEXT_AGENT_HANDOFF_*.md` | 主接手 |
| `04_DELIVERABLE_URL_TRACE_51.md` | URL 债 |
| `05_DELIVERABLE_CODE_DOC_AUDIT.md` | 代码审计 |
| `06_DELIVERABLE_OPENCLAW_*.md` | OpenClaw 观测 |
| `07_weekly_deepseek_prompt_matrix_*.md` | Flash/Pro 矩阵结论 |
| `08_weekly_pipeline_loss_chain_*.md` | 漏斗损失链 |
| `research_query_plan_a.md` / `plan_b.md` | LDR 任务提示词 |

## 产出（接手包内）

| 文件 | 说明 |
|------|------|
| [PLAN_A_DEEPRESEARCH_v2.md](./PLAN_A_DEEPRESEARCH_v2.md) | Golden schema、P0–P4 OKR、脚本映射、URL 清洗、决策表 |
| [PLAN_B_DEEPRESEARCH_v2.md](./PLAN_B_DEEPRESEARCH_v2.md) | WeeklyAtlasEntityContract、Resolver 五级阶梯、snapshot/observation、L0–L4 OKR |

## 复现命令

```powershell
docker exec ldr-wechat-research python /runner/run-artifact-research.py `
  --source-dir /source_pack/weekly_plan_deepresearch_20260519 `
  --query-file /source_pack/weekly_plan_deepresearch_20260519/research_query_plan_a.md `
  --model deepseek-v4-pro --max-docs 12 --max-chars 10000 --max-tokens 8000 --timeout 360 `
  --out /data/research_outputs/weekly_plan_a_deepseek_v4_pro_20260519.md
```

Plan B 将 `research_query_plan_a.md` 换为 `research_query_plan_b.md`，输出路径改为 `weekly_plan_b_...`。

## 档案落盘（2026-05-19 已补齐）

接手包内镜像目录：`archive/`（详见 [ARCHIVE_INDEX_20260519.md](./archive/ARCHIVE_INDEX_20260519.md)）

| 子目录 | 内容 |
|--------|------|
| `archive/ldr_raw_20260519/` | LDR 原始报告 Plan A + B（含 JSON 推理证据） |
| `archive/ldr_source_pack_20260519/` | 两轮 LDR 任务提示词 |
| `archive/deepseek_prompt_matrix_20260518/` | R1：DeepSeek Flash/Pro 矩阵评测结论 |
| `archive/p0_golden_20260519/` | P0：golden_set_v1 + baseline JSON/MD |

精炼稿（v2）仍在接手包根目录：`PLAN_A_DEEPRESEARCH_v2.md`、`PLAN_B_DEEPRESEARCH_v2.md`。

## 未做

- 未改 Stage7 / CloudRun / 小程序业务代码
- 未写入 mem0 / OpenHuman（可后续按需同步 v2 摘要）
- 未当作已批准实施 — 需用户/Hermes 拍板后进入 P1
