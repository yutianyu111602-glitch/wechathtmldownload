# Atlas Core 本轮执行日志

时间范围：2026-06-05 至 2026-06-06
执行者：Codex controller
执行模式：single-writer, report-local, no production DB writes

## 工作目标

把 DB1/DB2/DB3 的 Atlas 数据整合成 `Atlas Core` 核心库，并继续导出旧脚本可读的 serving/miniapp/index read models；第一阶段只做 report-local candidate，不毁坏源数据库。

## 安全前置

- 真实仓库核对：`C:\code\githubstar\wechathtmldownload`
- 当前分支：`wip/rescue-20260605-160743`
- 工作树：已有大量脏文件和未跟踪文件，本轮不清理、不 reset、不 revert。
- 用户明确约束：不能毁坏源数据库；字段必须兼容老库，因为很多程序和脚本吃老数据库。
- 本轮边界：只写 report-local candidate 和文档，不覆盖生产路径。

## 主要实现点

1. 新建 Atlas Core schema candidate。
2. 新建/完善 `build_atlas_core_candidate.py`。
3. 新建/完善 `export_atlas_core_to_serving_sqlite.py`。
4. 新建/完善 `run_atlas_core_candidate_safe.py`。
5. 增加 `atlas_core_common.py` 共享路径、hash、SQLite helper。
6. 增加 API shadow diff：`atlasCoreApiShadowDiff.mjs`。
7. `Stage7AtlasSqliteStore` 支持 `ATLAS_CORE_SQLITE_DB` opt-in。
8. `server.mjs` 保持默认旧 serving DB，只在 shadow/env opt-in 时读候选 read model。
9. 增加/更新 pytest 和 node test 覆盖。

## 迭代日志

### Round 1：初始 core + exporter

结果：

- 核心表可生成。
- 旧兼容导出可生成。
- 但 API shadow diff 出现 9 条回归。

问题类型：

- activity evidence/detail 缺口。
- graph window cache 不完整。
- search/profile rank 与旧库不一致。
- Loopy graph/org relation 覆盖不足。

### Round 2：补 graph/activity compat

动作：

- 增加 `compat_activity_event_detail`。
- 增加 `compat_activity_evidence_ref`。
- 增加 `compat_graph_window_cache`。
- exporter 优先保留旧 activity/graph 兼容字段。

结果：

- API shadow diff 回归从 9 降到 6。

### Round 3：补 legacy rank/profile/search compat

动作：

- 增加 `compat_canonical_subject`。
- 增加 `compat_dj_profile`。
- 增加 `compat_search_document`。
- 保留旧 `rank_score`、`source_count`、`source_article_count`、`public_state`、`search_text`。
- `search_document_fts` 保持旧 tokenizer 路线，并增加 unicode61 companion。

结果：

- API shadow diff 回归从 6 降到 2。
- 剩余集中在 Loopy graph seed。

### Round 4：补 organizer relation rollup

动作：

- 增加 `compat_dj_org_rollup`，保留旧 organizer graph 关系。
- exporter 将 org rollup 纳入 graph/read model。

结果：

- API shadow diff 回归从 2 降到 0。
- Loopy graph seed hash 与旧库一致。

### Round 5：修性能坑

问题：

- 旧 exporter 在 graph fallback 的 `NOT EXISTS` 上慢，原因是 fallback 前缺 `idx_graph_window_seed`。
- search fallback 类似需要 `idx_search_document_subject`。

动作：

- `graph_window_cache` compat copy 后立即 `CREATE INDEX IF NOT EXISTS idx_graph_window_seed`。
- `search_document` compat copy 后立即 `CREATE INDEX IF NOT EXISTS idx_search_document_subject`。
- 旧慢目录不再作为最终候选，最终目录为 `_legacy_rank_org_fix`。

结果：

- safe runner 完成。
- 生成最终候选。

## 关键命令

语法检查：

```powershell
python -m py_compile tools\stage7_rewrite\scripts\atlas_core_common.py tools\stage7_rewrite\scripts\build_atlas_core_candidate.py tools\stage7_rewrite\scripts\export_atlas_core_to_serving_sqlite.py tools\stage7_rewrite\scripts\run_atlas_core_candidate_safe.py
node --check services\weekly_activity_cloudrun\scripts\atlasCoreApiShadowDiff.mjs
node --check services\weekly_activity_cloudrun\src\server.mjs
node --check services\weekly_activity_cloudrun\src\stage7AtlasSqliteStore.mjs
```

pytest：

```powershell
python -m pytest tools\stage7_rewrite\tests\test_atlas_core_candidate.py -q
```

结果：`7 passed`

Node test：

```powershell
node --test --test-name-pattern "ATLAS_CORE_SQLITE_DB selects|serving search falls back" services\weekly_activity_cloudrun\tests\stage7SqliteLocal.test.mjs
```

结果：2 tests passed

safe runner：

```powershell
python tools\stage7_rewrite\scripts\run_atlas_core_candidate_safe.py --out-dir tools\stage7_rewrite\reports\atlas_core_candidate_20260605_legacy_rank_org_fix --readiness-out-dir tools\stage7_rewrite\reports\atlas_core_migration_readiness_20260605_legacy_rank_org_fix
```

API shadow diff：

```powershell
node services\weekly_activity_cloudrun\scripts\atlasCoreApiShadowDiff.mjs --old-serving-db reports\atlas_serving_time_overlay_span_split_search_date_refresh_candidate_20260527_2018\atlas_serving.sqlite --core-serving-db tools\stage7_rewrite\reports\atlas_core_candidate_20260605_legacy_rank_org_fix\atlas_serving.sqlite --out-dir tools\stage7_rewrite\reports\atlas_core_api_shadow_diff_20260605_legacy_rank_org_fix
```

API smoke：

```powershell
node services\weekly_activity_cloudrun\scripts\atlasServingLocalSmoke.mjs --candidate-db tools\stage7_rewrite\reports\atlas_core_candidate_20260605_legacy_rank_org_fix\atlas_serving.sqlite --out-dir tools\stage7_rewrite\reports\atlas_core_candidate_20260605_legacy_rank_org_fix\api_smoke
```

shadow read compare：

```powershell
python tools\stage7_rewrite\scripts\compare_atlas_core_serving_shadow_read.py --old-serving-db reports\atlas_serving_time_overlay_span_split_search_date_refresh_candidate_20260527_2018\atlas_serving.sqlite --new-serving-db tools\stage7_rewrite\reports\atlas_core_candidate_20260605_legacy_rank_org_fix\atlas_serving.sqlite --out-dir tools\stage7_rewrite\reports\atlas_core_serving_shadow_read_compare_20260605_legacy_rank_org_fix
```

search diagnosis：

```powershell
python tools\stage7_rewrite\scripts\diagnose_atlas_core_serving_search_regressions.py --old-serving-db reports\atlas_serving_time_overlay_span_split_search_date_refresh_candidate_20260527_2018\atlas_serving.sqlite --new-serving-db tools\stage7_rewrite\reports\atlas_core_candidate_20260605_legacy_rank_org_fix\atlas_serving.sqlite --out-dir tools\stage7_rewrite\reports\atlas_core_serving_search_diagnosis_20260605_legacy_rank_org_fix
```

## 文件变更概览

核心脚本：

- `tools/stage7_rewrite/scripts/atlas_core_common.py`
- `tools/stage7_rewrite/scripts/build_atlas_core_candidate.py`
- `tools/stage7_rewrite/scripts/export_atlas_core_to_serving_sqlite.py`
- `tools/stage7_rewrite/scripts/run_atlas_core_candidate_safe.py`

API/shadow：

- `services/weekly_activity_cloudrun/scripts/atlasCoreApiShadowDiff.mjs`
- `services/weekly_activity_cloudrun/src/stage7AtlasSqliteStore.mjs`
- `services/weekly_activity_cloudrun/src/server.mjs`

测试：

- `tools/stage7_rewrite/tests/test_atlas_core_candidate.py`
- `services/weekly_activity_cloudrun/tests/stage7SqliteLocal.test.mjs`

文档：

- `docs/handoffs/HANDOFF_ATLAS_CORE_CANDIDATE_20260605.md`
- `docs/handoffs/atlas-core-deepseektui-20260606/`
- `docs/DOCUMENTATION_INDEX.md`

## 本轮没有做的事

- 没有清理脏工作树。
- 没有覆盖生产 DB。
- 没有执行 DB3 S232D-4。
- 没有上传/提审/发布小程序。
- 没有部署 CloudRun/VPS/huaidj.club。
- 没有读取 secret、cookie、`.env` 或浏览器 profile。
- 没有使用 subagent fan-out。
