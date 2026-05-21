# 接手检查点 — 2026-05-19（2026-05-21 Sprint 1 更新）

> 精简续跑入口。执行计划见 **[PLAN_WEEKLY_MINIPROGRAM_UNIFIED.md](./PLAN_WEEKLY_MINIPROGRAM_UNIFIED.md)**；Sprint 1 closeout 见 [SPRINT1_GATE_CLOSEOUT_20260521.md](./SPRINT1_GATE_CLOSEOUT_20260521.md)；完整版见 [NEXT_AGENT_HANDOFF_WEEKLY_MINIPROGRAM_FULL.md](./NEXT_AGENT_HANDOFF_WEEKLY_MINIPROGRAM_FULL.md)

## 一句话

当前远端周活为 `weekly-api-039` / 158 条；Sprint 1 gate 已闭环：guardian 全绿、backendRawHits=0、strict duplicate/conflict=0、Golden 88 条中 20 verified。未执行 CloudRun 新部署、小程序新上传或微信提审。

## 权威数字（勿混旧数据）

| 项 | 值 |
|----|-----|
| API | `weekly-api-039` |
| 条数 / 窗口 | 158 / `2026-05-20..2026-06-03` |
| 小程序版 | `2026.05.21.1`（未提审） |
| guardian | ok=true；visibleHits=0；backendRawHits=0 |
| strict 去重 | duplicate=0；effective_duplicate=0；conflict=0 |
| lineup | 100/158；missing_lineup 58；hard_fail_count=0 |
| Golden | 88 条，20 verified，68 pending |
| baseline drift | `snapshot_drift_count=43`（5/19 seed 对 5/21 current 的自然漂移） |
| atlas snapshot | 209 lineup rows；alias_exact=63；fuzzy_multiple=90；no_match=56 |

## Sprint 1 新增/修正代码（已验证）

```
tools/stage7_rewrite/
  scripts/weekly_golden_lib.py
  scripts/bootstrap_weekly_golden_set.py
  scripts/evaluate_weekly_golden_baseline.py
  scripts/verify_weekly_golden_s1.py
  scripts/build_weekly_atlas_snapshot.py
  scripts/export_weekly_entity_observations.py
  weekly_atlas_bridge/          # resolver + snapshot + observations
  golden/golden_set_v1.jsonl
  tests/test_weekly_golden_baseline.py
  tests/test_verify_weekly_golden_s1.py
  weekly_atlas_bridge/tests/test_resolver.py
```

验证：guardian ok=true；strict duplicate/conflict 0/0/0；Python targeted **47/47 OK**；小程序 Node **29/29 OK**。

## 下一 agent 三件事

1. 进入 Sprint 2：`weekly_dedup_spec.v1.json` + Python/JS parity，确保 frontend_extra_merge=0
2. 处理 baseline drift：决定是否基于当前 158 包刷新/版本化 Golden
3. 继续保持上传/提审分离：提审必须单独用户批准

## 边界

小程序 ≠ 图谱；向量不进展示；不写 Neo4j/Qdrant production；未执行 CloudRun 新部署、小程序新上传、微信提审。
