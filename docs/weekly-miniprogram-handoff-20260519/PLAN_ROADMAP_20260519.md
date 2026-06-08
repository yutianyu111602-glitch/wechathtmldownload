# 周活计划路线图 — 2026-05-19

继承 [PLAN_A_DEEPRESEARCH_v2](./PLAN_A_DEEPRESEARCH_v2.md) / [PLAN_B_DEEPRESEARCH_v2](./PLAN_B_DEEPRESEARCH_v2.md)。  
档案：[archive/ARCHIVE_INDEX_20260519.md](./archive/ARCHIVE_INDEX_20260519.md)

## 当前阶段：**Phase II（见 [PLAN_WEEKLY_MINIPROGRAM_UNIFIED.md](./PLAN_WEEKLY_MINIPROGRAM_UNIFIED.md) §9）**

> P0 种子与 L1 bridge 已完成；蜂群 Task1–4 在分支 `feature/weekly-integrated-bridge`。后续以 Phase II 四 Sprint 为准。

## 历史阶段：**P0 已落地（种子）**

| P0 项 | 状态 | 证据 |
|-------|------|------|
| Golden 种子 ≥80 | ✅ 88 条 | `archive/p0_golden_20260519/golden_set_v1.jsonl` |
| Baseline 报告 | ✅ | `P0_BASELINE_REPORT_20260519.md` |
| 脚本 bootstrap + evaluate | ✅ | `tools/stage7_rewrite/scripts/bootstrap_weekly_golden_set.py` 等 |
| 人工 verified 标注 | ⏳ 0/88 | 填 `gold.*` + `annotation_status: verified` |
| L0 契约草案 | ✅ | `WeeklyAtlasEntityContract.md` |
| LDR/DeepSeek 档案落盘 | ✅ | `archive/` |
| 计划二 L1 bridge v0 | ✅ | `tools/stage7_rewrite/weekly_atlas_bridge/` + `PLAN_B_VECTOR_ATLAS_EXECUTION_20260519.md` |

## 后续阶段（未开始）

| 阶段 | 周期 | 计划一 | 计划二 | 退出门禁 |
|------|------|--------|--------|----------|
| **P1** | ~3 周 | field_evidence、build URL 清洗、guardian rawHits=0 | — | evidence schema；backendRawHits=0 |
| **P2** | ~4 周 | repair 评分制、regex 候选、Pro 扩面 | — | 无 hard_error 回归 |
| **P3** | ~3 周 | tier UI、verified bio | L1 resolver snapshot 只读 | UI review |
| **P4** | 持续 | 每周金标增量 | L3 observation 上行 | recall 周环比 |

## 建议下一动作（按优先级）

1. **人工金标**：每周标注 20–30 条 → `verified` → 重跑 `evaluate_weekly_golden_baseline.py`
2. **P1 URL 清洗**：改 `build_weekly_activity_miniprogram_api.py`（用户批准后）
3. **OpenClaw 首跑观测**：按 `DELIVERABLE_OPENCLAW_OBSERVATION_CHECKLIST.md`
4. **计划二 L2**：图谱侧导出 `atlas_alias_export.jsonl` + build 前挂载 snapshot（当前 seed 仅 ~5 艺人 → 103 包 89 行 mostly `no_match` 属预期）
5. **向量 review**：本机 Qdrant 可用时加 `--enable-vector-review`（不进展示）

## 明确不做（全阶段）

- 放松 duplicate / source URL 硬门
- LLM 自由 bio、向量自动进小程序 lineup
- 本线程内图谱 production 写入
