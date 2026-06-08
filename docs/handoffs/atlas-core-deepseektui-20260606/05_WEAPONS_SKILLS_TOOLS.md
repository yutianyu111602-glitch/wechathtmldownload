# 本轮使用的武器、Skill 与工具

目的：让 DeepSeekTUI 知道这轮工作用了什么、为什么用、哪些工具不能误用。

## Skill 路由

本轮文档沉淀阶段实际读取/使用：

| Skill | 用途 |
| --- | --- |
| `agent-skills-zh-router` | 中文任务自动路由，确认 handoff/SSOT/plan/docs/deepseek 相关 workflow。 |
| `local-skill-router` | 本地 skill 路由，确认最小 skill set，不启动长跑或危险动作。 |
| `handoff-writer` | 写接手文档，要求事实分 Confirmed/Hypothesis/Unverified/Blocked。 |
| `ssot-handoff-reporter` | 产出可接手的 SSOT/handoff 报告，并更新文档索引。 |
| `documentation-and-adrs` | 记录为什么这样设计、权衡、替代方案和未来维护入口。 |
| `planning-and-task-breakdown` | 把 DeepSeekTUI 后续优化拆成有验收标准的 P0-P5。 |
| `deepseek-deep-dream-sidecar` | 明确 DeepSeekTUI 是候选生成/审阅 sidecar，不是 authority 或生产写入者。 |

本任务早期用户显式提到/约束的 superpowers 路线：

| Route | 在本任务中的作用 |
| --- | --- |
| `superpowers:brainstorming` | 用于最初 DB1/DB2/DB3 解耦整合去重方案发散。 |
| `superpowers:writing-plans` | 用于把方案拆成 Atlas Core 分阶段计划。 |
| `superpowers:executing-plans` | 用于按用户批准的 implementation plan 执行。 |
| `superpowers:verification-before-completion` | 用于不把未验证状态说成完成。 |

## 主控原则

- single writer：所有写文件动作由 Codex 主线程执行。
- no subagent fan-out：没有启动多个 subagent，避免 DB/file/process contention。
- report-local only：所有 DB 候选只写 report-local 目录。
- source hash guard：每轮核对源 DB hash，不让源库被修改。
- legacy compatibility first：旧字段、旧 ID、旧 rank、旧 read model 优先。

## 核心脚本武器

| Script | 作用 |
| --- | --- |
| `tools/stage7_rewrite/scripts/atlas_core_common.py` | Atlas Core 共享 helper：路径、hash、SQLite、安全读写辅助。 |
| `tools/stage7_rewrite/scripts/build_atlas_core_candidate.py` | 构建 `atlas_core.sqlite` 和 core/compat 表。 |
| `tools/stage7_rewrite/scripts/export_atlas_core_to_serving_sqlite.py` | 从 core 导出候选 `atlas_serving.sqlite`。 |
| `tools/stage7_rewrite/scripts/run_atlas_core_candidate_safe.py` | 一键 safe runner：构建、导出、readback、leak/source hash guard。 |
| `services/weekly_activity_cloudrun/scripts/atlasCoreApiShadowDiff.mjs` | 旧 serving vs core-export serving 的 API shadow diff。 |
| `services/weekly_activity_cloudrun/scripts/atlasServingLocalSmoke.mjs` | 本地 API smoke，验证候选 serving DB 可被旧 API 打开。 |
| `tools/stage7_rewrite/scripts/compare_atlas_core_serving_shadow_read.py` | serving read model 覆盖率 shadow compare。 |
| `tools/stage7_rewrite/scripts/diagnose_atlas_core_serving_search_regressions.py` | 搜索/FTS 诊断，确认 tokenizer 和 OIL/Loopy 行为。 |

## 修改过的 API/Store 文件

| File | 作用 |
| --- | --- |
| `services/weekly_activity_cloudrun/src/stage7AtlasSqliteStore.mjs` | 支持 `ATLAS_CORE_SQLITE_DB` opt-in read model。 |
| `services/weekly_activity_cloudrun/src/server.mjs` | 保持默认旧 DB；shadow/env opt-in 才读候选 DB。 |
| `services/weekly_activity_cloudrun/tests/stage7SqliteLocal.test.mjs` | 增加 env opt-in 和 serving search fallback 测试。 |

## 测试武器

| Command | 验证点 |
| --- | --- |
| `python -m py_compile ...` | Python 脚本语法。 |
| `python -m pytest tools\stage7_rewrite\tests\test_atlas_core_candidate.py -q` | core schema/exporter/safety 单测，结果 `7 passed`。 |
| `node --check ...` | Node 脚本和 API/store 文件语法。 |
| `node --test --test-name-pattern "ATLAS_CORE_SQLITE_DB selects|serving search falls back" ...` | env opt-in 与旧搜索 fallback。 |
| `run_atlas_core_candidate_safe.py` | 最终 report-local 安全执行。 |
| `atlasCoreApiShadowDiff.mjs` | 20 path API shadow diff，0 regression。 |
| `atlasServingLocalSmoke.mjs` | 本地 API smoke，`ok=true`。 |

## 本轮没有使用的武器

- 没有使用 Browser/Chrome 自动化。
- 没有使用 GitHub connector。
- 没有使用 CloudBase/WeChat DevTools upload。
- 没有使用 Docker/OpenClaw worker。
- 没有使用 provider/geocode/model API。
- 没有读取 `.env`、cookies、secret。
- 没有启动 DeepSeekTUI 进程或 DeepSeek API 调用。

## DeepSeekTUI 可以复用的武器

优先复用：

- `atlasCoreApiShadowDiff.mjs`
- `compare_atlas_core_serving_shadow_read.py`
- `diagnose_atlas_core_serving_search_regressions.py`
- `identity_resolution_cases.jsonl`
- `legacy_mapping_gaps.jsonl`
- `atlas_core_safe_execution_report.json`

不要复用为生产执行：

- DB write scripts。
- promotion scripts。
- deploy/upload/release scripts。
- crawler/avatar/outlink batch。
- 未经 controller approval 的 OpenClaw runtime。
