# P0 执行状态 — 2026-05-19

继承 `PLAN_A_DEEPRESEARCH_v2` / `PLAN_B_DEEPRESEARCH_v2` 的 P0 阶段。

## 档案落盘

| 类型 | 已落盘 | 路径 |
|------|--------|------|
| LDR 原始（Plan A/B） | ✅ | `archive/ldr_raw_20260519/` |
| LDR 提示词 | ✅ | `archive/ldr_source_pack_20260519/` |
| DeepSeek 矩阵 R1 | ✅ | `archive/deepseek_prompt_matrix_20260518/` |
| P0 golden + baseline | ✅ | `archive/p0_golden_20260519/` |
| 总索引 | ✅ | `archive/ARCHIVE_INDEX_20260519.md` |

## 已完成（本 session）

| 交付物 | 路径 |
|--------|------|
| Golden schema | `tools/stage7_rewrite/golden/GOLDEN_SET_SCHEMA.md` |
| 引导脚本 | `tools/stage7_rewrite/scripts/bootstrap_weekly_golden_set.py` |
| Baseline 评测 | `tools/stage7_rewrite/scripts/evaluate_weekly_golden_baseline.py` |
| 共享库 | `tools/stage7_rewrite/scripts/weekly_golden_lib.py` |
| 单测 | `tools/stage7_rewrite/tests/test_weekly_golden_baseline.py` |
| L0 契约 | `docs/weekly-miniprogram-handoff-20260519/WeeklyAtlasEntityContract.md` |

## 待人工（P0 退出门禁）

| 项 | 状态 |
|----|------|
| Golden ≥80 条种子 | 脚本已生成 → `D:\downstream_results\golden\golden_set_v1.jsonl` |
| 人工 verified 标注 | **pending**（全部 `annotation_status: pending`） |
| inter-annotator agreement | 未开始 |
| baseline 报告 review | 见 `P0_BASELINE_REPORT_20260519.md` |

## 一键命令

```powershell
cd C:\code\githubstar\wechathtmldownload

# 1) 从 20260519 发布包引导 88 条金标种子
python tools\stage7_rewrite\scripts\bootstrap_weekly_golden_set.py

# 2) 生成 baseline（不调 DeepSeek）
python tools\stage7_rewrite\scripts\evaluate_weekly_golden_baseline.py

# 3) 单测
python -m unittest tools.stage7_rewrite.tests.test_weekly_golden_baseline -v
```

## 不在 P0（勿提前）

- build 层 URL 清洗（P1）
- repair 评分制（P2）
- ~~`weekly_atlas_bridge` 代码实现（计划二 L1）~~ → **已完成**（见 `PLAN_B_VECTOR_ATLAS_EXECUTION_20260519.md`）
