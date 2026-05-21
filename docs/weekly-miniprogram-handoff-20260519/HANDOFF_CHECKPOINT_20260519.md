# 接手检查点 — 2026-05-19（2026-05-21 Sprint 1–3 本地闭环更新）

> 精简续跑入口。执行计划见 **[PLAN_WEEKLY_MINIPROGRAM_UNIFIED.md](./PLAN_WEEKLY_MINIPROGRAM_UNIFIED.md)**；Sprint 1 closeout 见 [SPRINT1_GATE_CLOSEOUT_20260521.md](./SPRINT1_GATE_CLOSEOUT_20260521.md)；Sprint 2 parity closeout 见 [SPRINT2_DEDUP_PARITY_CLOSEOUT_20260521.md](./SPRINT2_DEDUP_PARITY_CLOSEOUT_20260521.md)；Sprint 3 local closeout 见 [SPRINT3_CLUB_SOURCE_CLOSEOUT_20260521.md](./SPRINT3_CLUB_SOURCE_CLOSEOUT_20260521.md)；去重与推文整合逻辑见 [DEDUP_SOURCE_INTEGRATION_LOGIC_20260521.md](./DEDUP_SOURCE_INTEGRATION_LOGIC_20260521.md)；文档/代码/计划生命周期审计见 [DOC_CODE_PLAN_SYNC_AUDIT_20260521.md](./DOC_CODE_PLAN_SYNC_AUDIT_20260521.md)。[NEXT_AGENT_HANDOFF_WEEKLY_MINIPROGRAM_FULL.md](./NEXT_AGENT_HANDOFF_WEEKLY_MINIPROGRAM_FULL.md) 是 2026-05-19 长版历史接手证据，不再作为当前数字入口。

## 一句话

既有线上记录为 `weekly-api-039` / 158 条；本线程本地已闭环 Sprint 1–3 的可执行切片：backendRawHits=0、strict duplicate/conflict=0、dedupe parity PASS、重复推文 `merge_provenance` + source map redirect、详情/俱乐部页来源推文去重展示、`organizer_key/club_profile` API 契约、city switchTab、venue/artist 分页、saved lang。2026-05-21 本次 guardian 复验整体为 `ok=false`，原因是公网 API probe 超时与 daily queue exporter refresh 无有效账号，不代表本地 158 包重复/URL 门禁失败。未执行 CloudRun 新部署、小程序新上传或微信提审。

## 权威数字（勿混旧数据）

| 项 | 值 |
|----|-----|
| API | `weekly-api-039` |
| 条数 / 窗口 | 158 / `2026-05-20..2026-06-03` |
| 小程序版 | `2026.05.21.1`（既有开发版；本线程未新上传；未提审） |
| guardian 本地检查 | visibleHits=0；backendRawHits=0；frontend real data=158；mini_program_tests=35 pass |
| guardian 整体复验 | ok=false；public_api_current_probe timeout；daily_queue_exporter_refresh_effective=false |
| strict 去重 | duplicate=0；effective_duplicate=0；conflict=0 |
| lineup | 100/158；missing_lineup 58；hard_fail_count=0 |
| Golden | 88 条，20 conservative snapshot verified，68 pending |
| baseline drift | `snapshot_drift_count=43`（5/19 seed 对 5/21 current 的自然漂移） |
| atlas snapshot | 209 lineup rows；alias_exact=63；fuzzy_multiple=90；no_match=56 |
| Sprint 2 parity | `weekly_dedup_spec.v1.json`；Python/mini-program/CloudRun parity PASS；frontend_extra_merge=0 |
| Sprint 2 source integration | duplicate source map redirect；retained event `merge_provenance`；temp current repair hard_fail=0 |
| Sprint 3 local UI/API | `organizer_key` + `club_profile` on current/detail/batch；detail/venue `SOURCE ARTICLES`；venue key match；city switchTab；venue/artist pagination；saved lang |

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

## Sprint 3 小程序/Atlas 交叉本地切片（已验证）

```
apps/weekly_activity_miniprogram/utils/format.js
apps/weekly_activity_miniprogram/utils/sourceArticles.js
apps/weekly_activity_miniprogram/pages/detail/detail.js
apps/weekly_activity_miniprogram/pages/detail/detail.wxml
apps/weekly_activity_miniprogram/pages/detail/detail.wxss
apps/weekly_activity_miniprogram/pages/venue/venue.js
apps/weekly_activity_miniprogram/pages/artist/artist.js
apps/weekly_activity_miniprogram/pages/city/city.js
apps/weekly_activity_miniprogram/pages/index/index.js
apps/weekly_activity_miniprogram/pages/saved/saved.js
services/weekly_activity_cloudrun/src/dataStore.mjs
services/weekly_activity_cloudrun/tests/weeklyApi.test.mjs
apps/weekly_activity_miniprogram/tests/source-articles.test.cjs
apps/weekly_activity_miniprogram/tests/page-source-routing.test.cjs
apps/weekly_activity_miniprogram/tests/format-quality.test.cjs
```

验证：CloudRun API tests **30/30 pass**；CloudRun full tests **39/39 pass**；mini-program non-DevTools CJS/static tests pass；`stage7_safe_handoff_verify.ps1` **PASS**（Python targeted **354 passed**，CloudRun Stage7 **39 pass**）；当前 158 包 strict duplicate/effective/conflict **0/0/0**。DevTools 真机/上传未执行。

## 下一 agent 三件事

1. 修复/等待公网 API probe 与 daily queue exporter refresh，再复跑 guardian；不要把本次 `ok=false` 误判为本地 158 包去重失败
2. 等待/生成下一次 OpenClaw 新包后，复跑 repair + strict audit，确认 source provenance 不丢、去重不新增重复卡
3. 处理 baseline drift：决定是否基于当前 158 包刷新/版本化 Golden；20 verified 不是人工/inter-annotator 金标
4. Sprint 4 需要 G0 alias export/new snapshot/dev upload；上传/提审必须单独用户批准

## 边界

小程序 ≠ 图谱；向量不进展示；不写 Neo4j/Qdrant production；未执行 CloudRun 新部署、小程序新上传、微信提审。
