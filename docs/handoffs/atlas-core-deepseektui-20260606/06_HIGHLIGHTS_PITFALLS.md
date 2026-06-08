# Atlas Core 亮点与坑点

## 亮点

### 1. 核心库和旧库兼容没有互相牺牲

核心库建立了 `core_entity`、`core_event`、`core_source_ref`、`entity_legacy_id`、`entity_relation_edge`、`external_link_evidence`、`identity_resolution_case` 等统一事实层。

同时，旧 serving/miniapp/index 导出继续保留旧表、旧字段、旧 ID 和旧 shape，让旧脚本能继续吃老数据库格式。

### 2. report-local 安全边界清楚

最终候选全部在：

```text
tools/stage7_rewrite/reports/atlas_core_candidate_20260605_legacy_rank_org_fix/
```

没有覆盖 production DB，没有写 DB3，没有上传/发布。

### 3. API shadow diff 从 9 回归压到 0

关键修复路径：

- activity evidence/detail compat
- graph window cache compat
- canonical subject/profile/search document compat
- organizer relation rollup compat

这说明旧消费者真正依赖的不是单个 core fact，而是 read model 的 rank、source count、graph cache 和 org rollup。

### 4. `ATLAS_CORE_SQLITE_DB` 是 opt-in

默认仍读旧 `atlas_serving.sqlite`。只有设置 env var 才读 core-export serving read model。这样可以做 shadow，不会误切线上。

### 5. 性能坑已显式修掉

`NOT EXISTS` fallback 前补了关键索引：

- `idx_graph_window_seed`
- `idx_search_document_subject`

避免 exporter 在 GB 级 sqlite 上长时间卡住。

## 坑点

### 1. 不要把 `atlas_core.sqlite` 直接当 API serving DB

当前 API/store 的 opt-in 目标是 core 导出的 `atlas_serving.sqlite`，不是 `atlas_core.sqlite`。变量名 `ATLAS_CORE_SQLITE_DB` 有点误导，但第一阶段是为了接入 core-export read model。

### 2. `dataset_id` 日期看起来旧

manifest 里的 `dataset_id` 是 `atlas_core_candidate_20260604`，但最终目录是 `20260605_legacy_rank_org_fix`。这是原计划 dataset id 沿用，不代表最终候选目录错。

### 3. `dj_venue_rollup` count 大于旧库

最终 serving 导出 `dj_venue_rollup=161810`，旧库曾是 `137101`。当前 shadow compare 没有关键覆盖回退；如果未来要求完全一致，要单独设计 `dj_venue_rollup` exact-first 或 difference budget。

### 4. 中文 FTS 不是 trigram 主表单独解决

`search_document_fts` tokenizer 是 `trigram`，中文城市查询在 trigram 表可能为 0；unicode61 companion 有中文 counts。这是已知设计，不要误判为 leak 或搜索失败。

### 5. S119/S120 external-link 不能直连 DB3 dj_id

`entity_search_id` 必须先过 `entity_legacy_id`。直接 join DB3 `dj_profile.dj_id` 会再次制造三库身份漂移。

### 6. 348 identity blockers 仍没释放

`identity_resolution_case=348` 不是已合并清单。它只是承接 blocker：

- 38 source-backed candidates
- 93 manual review
- 217 external evidence required
- approved/write allowed 仍为 0

### 7. 兼容表看起来不美观，但必要

`compat_*` 表不是最终理想 schema，但它们保护旧消费者。不要为了 schema 漂亮删除它们，否则旧 API/search/profile/graph 会回归。

### 8. 当前工作树非常脏

不要用全量 `git status` 的巨大未跟踪列表判断本轮改动范围。只看本轮 target files 和文档包。不要 reset/clean。

### 9. 不要复活旧慢目录

旧 partial/slow 目录不是最终候选。最终候选只认：

```text
atlas_core_candidate_20260605_legacy_rank_org_fix
```

### 10. Readiness gaps 是可见风险，不是失败

DB2->DB3 relation/source/event/external_link gaps 仍需要解释包。第一阶段的目标是显式暴露这些 gaps，而不是偷偷写 DB3。

## DeepSeekTUI 最容易误判的三件事

1. 看到 API shadow diff 0 就认为可以切生产。
2. 看到 38 source-backed candidates 就认为可以执行 DB3 S232D-4。
3. 看到 core schema 表完整就删除 compat read model。

正确做法：继续 shadow、扩 coverage、生成审批包，等 Codex/用户 gate。
