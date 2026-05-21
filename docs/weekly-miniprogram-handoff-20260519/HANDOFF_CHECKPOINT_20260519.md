# 接手检查点 — 2026-05-19（2026-05-21 Sprint 1 + Sprint 2 parity 更新）

> 精简续跑入口。执行计划见 **[PLAN_WEEKLY_MINIPROGRAM_UNIFIED.md](./PLAN_WEEKLY_MINIPROGRAM_UNIFIED.md)**；Sprint 1 closeout 见 [SPRINT1_GATE_CLOSEOUT_20260521.md](./SPRINT1_GATE_CLOSEOUT_20260521.md)；Sprint 2 parity closeout 见 [SPRINT2_DEDUP_PARITY_CLOSEOUT_20260521.md](./SPRINT2_DEDUP_PARITY_CLOSEOUT_20260521.md)；去重与推文整合逻辑见 [DEDUP_SOURCE_INTEGRATION_LOGIC_20260521.md](./DEDUP_SOURCE_INTEGRATION_LOGIC_20260521.md)；完整版见 [NEXT_AGENT_HANDOFF_WEEKLY_MINIPROGRAM_FULL.md](./NEXT_AGENT_HANDOFF_WEEKLY_MINIPROGRAM_FULL.md)

## 一句话

当前远端周活为 `weekly-api-039` / 158 条；Sprint 1 gate 已闭环：guardian 全绿、backendRawHits=0、strict duplicate/conflict=0、Golden 88 条中 20 条为 conservative snapshot verified。Sprint 2 已完成 `weekly_dedup_spec.v1.json` + Python/JS/CloudRun parity，`frontend_extra_merge=0`；并补齐重复推文合并的 `merge_provenance` 与 source map redirect，确保同一事件不重复发卡且不丢来源推文。未执行 CloudRun 新部署、小程序新上传或微信提审。

## 权威数字（勿混旧数据）

| 项 | 值 |
|----|-----|
| API | `weekly-api-039` |
| 条数 / 窗口 | 158 / `2026-05-20..2026-06-03` |
| 小程序版 | `2026.05.21.1`（未提审） |
| guardian | ok=true；visibleHits=0；backendRawHits=0 |
| strict 去重 | duplicate=0；effective_duplicate=0；conflict=0 |
| lineup | 100/158；missing_lineup 58；hard_fail_count=0 |
| Golden | 88 条，20 conservative snapshot verified，68 pending |
| baseline drift | `snapshot_drift_count=43`（5/19 seed 对 5/21 current 的自然漂移） |
| atlas snapshot | 209 lineup rows；alias_exact=63；fuzzy_multiple=90；no_match=56 |
| Sprint 2 parity | `weekly_dedup_spec.v1.json`；Python/mini-program/CloudRun parity PASS；frontend_extra_merge=0 |
| Sprint 2 source integration | duplicate source map redirect；retained event `merge_provenance`；temp current repair hard_fail=0 |

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

## Sprint 2 parity 新增/修正代码（已验证）

```
tools/stage7_rewrite/fixtures/weekly_dedup_spec.v1.json
tools/stage7_rewrite/tests/test_weekly_dedup_spec_parity.py
apps/weekly_activity_miniprogram/tests/dedup-parity.test.cjs
apps/weekly_activity_miniprogram/utils/format.js
services/weekly_activity_cloudrun/tests/dedupParity.test.mjs
services/weekly_activity_cloudrun/src/dataStore.mjs
```

验证：Python L2 parity + repair conflict **10/10 OK**；小程序 Node **30/30 pass**；CloudRun Node **38/38 pass**；当前 158 包 strict duplicate/conflict **0/0/0**。

## Sprint 2 推文整合新增/修正代码（已验证）

```
tools/stage7_rewrite/scripts/repair_weekly_release_conflicts.py
tools/stage7_rewrite/tests/test_repair_weekly_release_conflicts.py
docs/weekly-miniprogram-handoff-20260519/DEDUP_SOURCE_INTEGRATION_LOGIC_20260521.md
docs/weekly-miniprogram-handoff-20260519/SPRINT2_SOURCE_INTEGRATION_CLOSEOUT_20260521.md
```

验证：重复合并会在 retained event 写 `merge_provenance`；被合并 source map 条目 redirect 到 retained event；当前 158 包临时 repair 后 `missing_lineup=58`、`hard_fail=0`。

## 下一 agent 三件事

1. 继续 Sprint 2：repair soft scoring impact review，确认 missing_lineup 下降不引入 hard_fail
2. 处理 baseline drift：决定是否基于当前 158 包刷新/版本化 Golden；20 verified 不是人工/inter-annotator 金标
3. 做 merge provenance 写入/抽样，然后再跑 repair 新包 + strict audit；上传/提审必须单独用户批准

## 边界

小程序 ≠ 图谱；向量不进展示；不写 Neo4j/Qdrant production；未执行 CloudRun 新部署、小程序新上传、微信提审。
