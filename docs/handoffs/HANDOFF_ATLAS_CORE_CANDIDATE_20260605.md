# Atlas Core Candidate Handoff

时间：2026-06-05 18:25 CST
工作区：C:\code\githubstar\wechathtmldownload
分支：wip/rescue-20260605-160743
状态：report-local candidate ready, production promotion not approved

## 一句话接手口径

Atlas Core 第一阶段候选已生成在 report-local 目录，旧 DB1/DB2/DB3 源库 hash guard 全部稳定，旧 API shadow diff 已从 9 条回归降到 0 条；不得把这理解为生产切换。

## 先读入口

1. docs/DOCUMENTATION_INDEX.md
2. docs/handoffs/HANDOFF_ATLAS_CORE_CANDIDATE_20260605.md
3. tools/stage7_rewrite/reports/atlas_core_candidate_20260605_legacy_rank_org_fix/atlas_core_safe_execution_report.json
4. tools/stage7_rewrite/reports/atlas_core_api_shadow_diff_20260605_legacy_rank_org_fix/atlas_core_api_shadow_diff_summary.md

## 当前事实

### Confirmed

- 最终候选目录：tools/stage7_rewrite/reports/atlas_core_candidate_20260605_legacy_rank_org_fix/.
- 生成物存在：atlas_core.sqlite, atlas_serving.sqlite, atlas_miniapp.sqlite, atlas_index.json.gz, atlas_core_manifest.json, atlas_core_safe_execution_report.json.
- safe runner 决策：atlas_core_safe_execution_passed，blockers 为空，source_hashes_unchanged=true。
- 源库 hash 未变化：DB1 0fbb77fd8b70e5c3591751625d4befd4487bc376a08b30b71f12e2874d136cab；DB2 fc6f565e28a04a142afad140c5f0b8634e07cc8a5002d74f00994c898fe812fe；DB3 0b9e580e1e0fa0a85aec10525db9646f14a1593cbccc7a0a4d798f90014fcda1；S119 sidecar 2dba9308acde15b7c3b0af89562b4394e685639a8d307274b2630d6c27314934；S232D3B8 5c05413a98faeb41d3e642aa7e1907dc15c73674a8c3dfaa0dd4d8fdb2bbc997。
- core readback counts：core_entity 82878, core_event 508049, entity_event_edge 1285827, entity_relation_edge 701396, external_link_evidence 748, identity_resolution_case 348。
- compat 快照进入 core：compat_canonical_subject 82878, compat_dj_profile 53555, compat_search_document 590927, compat_dj_org_rollup 323335, compat_graph_window_cache 53555, compat_activity_event_detail 196, compat_activity_evidence_ref 2181。
- identity gate 仍是 report-only：source-backed 38, manual review 310, external evidence 217, approved_for_s232d4_count 0, db_write_allowed_now_count 0。
- serving exporter readback：canonical_subject 82878, dj_profile 53555, performance_event 508049, dj_event 1285827, dj_relation_rollup 701396, evidence_ref 130591, graph_window_cache 53555, search_document 590927。
- miniapp exporter readback：subject 82878, dj_profile 53555, dj_event 1285827, dj_collaborator 701396, source_ref 130591, redirect 1668, disposition 348。
- atlas_index.json.gz shape 保持 v4，包含 subjects/profiles/events/collabs/dj_venues/source_refs 等旧字段集合。
- API shadow diff：tools/stage7_rewrite/reports/atlas_core_api_shadow_diff_20260605_legacy_rank_org_fix/atlas_core_api_shadow_diff_report.json，decision atlas_core_api_shadow_diff_ready_report_only，20 paths, regression_finding_count 0, leak_finding_count 0, source_hashes_unchanged true。
- API smoke：tools/stage7_rewrite/reports/atlas_core_candidate_20260605_legacy_rank_org_fix/api_smoke/api_smoke.json，failed_api_checks=[]；browser_smoke.json failed_browser_checks=[]。
- shadow read compare：tools/stage7_rewrite/reports/atlas_core_serving_shadow_read_compare_20260605_legacy_rank_org_fix/atlas_core_serving_shadow_read_compare_report.json，blockers 为空，key coverage regression 0，search regression 0，leak 0。
- search diagnosis：tools/stage7_rewrite/reports/atlas_core_serving_search_diagnosis_20260605_legacy_rank_org_fix/atlas_core_serving_search_regression_diagnosis_report.json，OIL/Loopy old/new FTS counts一致，tokenizer 未变。
- 18:25 CST 检查时没有遗留 atlas_core candidate builder/exporter 进程；此前慢进程来自旧未索引 NOT EXISTS 路径，已由代码修复并被最终候选替代。

### Unverified

- 未做生产 pointer 切换。
- 未覆盖现有 production atlas_serving.sqlite、atlas_miniapp.sqlite 或 atlas_index.json.gz。
- 未运行 mini-program upload/review/release。
- 未运行 CloudRun/VPS/huaidj.club deploy。
- 未执行 DB3 S232D-4 identity merge write。
- readiness audit 仍报告 DB2->DB3 映射缺口，尤其 relation/source/event/external_link 的 join coverage，不是生产切换绿灯。

### Blocked

- 生产切换仍需用户明确批准。
- DB3 relation integrity / S232D-4 写入仍 blocked，approved_for_s232d4_count 必须保持 0，直到单独审批门通过。

## 本轮改动

- 新增/完善 Atlas Core candidate 机制和 safe runner/exporter 验证。
- core schema 新增兼容快照层：compat_canonical_subject, compat_dj_profile, compat_search_document, compat_dj_org_rollup, compat_activity_event_detail, compat_activity_evidence_ref, compat_graph_window_cache。
- builder 从 DB2 只读复制旧 read-model 兼容表，防止旧 API/script 因 rank/source/profile/org rollup 丢失而回退。
- serving exporter 先投影 compat 旧表，再用 core 新 facts 补缺失；旧字段名和类型不改。
- serving exporter 修复两个性能坑：graph fallback 前提前建立 idx_graph_window_seed；search_document compat copy 后提前建立 idx_search_document_subject。
- Stage7AtlasSqliteStore/server 支持 ATLAS_CORE_SQLITE_DB opt-in read model；默认仍读旧 serving DB。
- 新增 API shadow diff 脚本：services/weekly_activity_cloudrun/scripts/atlasCoreApiShadowDiff.mjs。

## 验证命令

```powershell
python -m py_compile tools\stage7_rewrite\scripts\atlas_core_common.py tools\stage7_rewrite\scripts\build_atlas_core_candidate.py tools\stage7_rewrite\scripts\export_atlas_core_to_serving_sqlite.py tools\stage7_rewrite\scripts\run_atlas_core_candidate_safe.py
python -m pytest tools\stage7_rewrite\tests\test_atlas_core_candidate.py -q
python tools\stage7_rewrite\scripts\run_atlas_core_candidate_safe.py --out-dir tools\stage7_rewrite\reports\atlas_core_candidate_20260605_legacy_rank_org_fix --readiness-out-dir tools\stage7_rewrite\reports\atlas_core_migration_readiness_20260605_legacy_rank_org_fix
node services\weekly_activity_cloudrun\scripts\atlasCoreApiShadowDiff.mjs --old-serving-db reports\atlas_serving_time_overlay_span_split_search_date_refresh_candidate_20260527_2018\atlas_serving.sqlite --core-serving-db tools\stage7_rewrite\reports\atlas_core_candidate_20260605_legacy_rank_org_fix\atlas_serving.sqlite --out-dir tools\stage7_rewrite\reports\atlas_core_api_shadow_diff_20260605_legacy_rank_org_fix
node services\weekly_activity_cloudrun\scripts\atlasServingLocalSmoke.mjs --candidate-db tools\stage7_rewrite\reports\atlas_core_candidate_20260605_legacy_rank_org_fix\atlas_serving.sqlite --out-dir tools\stage7_rewrite\reports\atlas_core_candidate_20260605_legacy_rank_org_fix\api_smoke
python tools\stage7_rewrite\scripts\compare_atlas_core_serving_shadow_read.py --old-serving-db reports\atlas_serving_time_overlay_span_split_search_date_refresh_candidate_20260527_2018\atlas_serving.sqlite --new-serving-db tools\stage7_rewrite\reports\atlas_core_candidate_20260605_legacy_rank_org_fix\atlas_serving.sqlite --out-dir tools\stage7_rewrite\reports\atlas_core_serving_shadow_read_compare_20260605_legacy_rank_org_fix
python tools\stage7_rewrite\scripts\diagnose_atlas_core_serving_search_regressions.py --old-serving-db reports\atlas_serving_time_overlay_span_split_search_date_refresh_candidate_20260527_2018\atlas_serving.sqlite --new-serving-db tools\stage7_rewrite\reports\atlas_core_candidate_20260605_legacy_rank_org_fix\atlas_serving.sqlite --out-dir tools\stage7_rewrite\reports\atlas_core_serving_search_diagnosis_20260605_legacy_rank_org_fix
```

## 下一步

1. 若继续 Phase F，使用 ATLAS_CORE_SQLITE_DB 指向最终候选 atlas_serving.sqlite 做更多 shadow mode 读对比；默认运行仍应读旧 atlas_serving.sqlite。
2. 扩充 API shadow diff 路径集，覆盖更多 DJ、venue、organizer、source evidence lookup 和 HUAIDJ Atlas 页面场景。
3. 对 readiness audit 中 DB2->DB3 的 relation/source/event/external_link 缺口分批生成解释包，不直接写 DB3。
4. 若准备 production promotion，先跑 npm run weekly:deploy-upload:preflight 并要求 required failed 为 0，再等用户明确批准 pointer 切换。

## 禁止动作

- 不要覆盖生产 atlas_serving.sqlite、atlas_miniapp.sqlite、atlas_index.json.gz。
- 不要执行 DB3 S232D-4 merge/write。
- 不要上传、review、release 小程序。
- 不要部署 CloudRun/VPS/huaidj.club。
- 不要把 report-local ready 当作 production ready。
- 不要清理或 reset 当前脏工作树。
