# Atlas Core 验收与接手报告

时间：2026-06-06 15:56 CST
对象：Atlas Core DB1/DB2/DB3 三库合一第一阶段 report-local candidate
验收状态：shadow/read-model candidate accepted; production switch not accepted

## 验收结论

Confirmed：最终候选目录 `tools/stage7_rewrite/reports/atlas_core_candidate_20260605_legacy_rank_org_fix/` 已生成核心库和全部旧兼容导出，source hash guard 稳定，安全报告通过，API shadow diff 无回归。

Unverified：这不是生产切换证明；没有覆盖生产 DB，没有小程序上传/提审/发布，没有 CloudRun/VPS/huaidj.club 部署，没有 DB3 S232D-4 写入。

Blocked：生产切换必须等 DB3 relation integrity / identity approval gate、weekly deploy-upload preflight、legacy consumer smoke、miniapp tests、Atlas web smoke 和用户明确批准。

## 已验收范围

- Phase A/B/C/F 的 report-local candidate 路线。
- `atlas_core.sqlite` 核心库候选。
- `atlas_serving.sqlite` 旧 serving read model 候选。
- `atlas_miniapp.sqlite` 小程序 sqlite 候选。
- `atlas_index.json.gz` 小程序压缩索引候选。
- 旧 API shape shadow diff。
- `Stage7AtlasSqliteStore` opt-in shadow read route。
- source hash guard、leak scan、readback count、compat table existence。

## 未验收范围

- DB1/DB2/DB3 任意生产库写入。
- production pointer 切换。
- 小程序 CloudBase sync、upload、review、release。
- CloudRun/VPS/huaidj.club deploy。
- DB3 S232D-4 identity merge write。
- OpenClaw external-link 候选直接投影到 DB3。
- 348 same-normalized identity blockers 的自动合并。

## 最终候选路径

Windows：

```text
C:\code\githubstar\wechathtmldownload\tools\stage7_rewrite\reports\atlas_core_candidate_20260605_legacy_rank_org_fix
```

WSL：

```text
/mnt/c/code/githubstar/wechathtmldownload/tools/stage7_rewrite/reports/atlas_core_candidate_20260605_legacy_rank_org_fix
```

## 核心 readback 计数

来自 `atlas_core_safe_execution_report.json`：

| Table | Count |
| --- | ---: |
| `core_entity` | 82878 |
| `core_event` | 508049 |
| `core_source_ref` | 130591 |
| `entity_legacy_id` | 271006 |
| `entity_event_edge` | 1285827 |
| `entity_relation_edge` | 701396 |
| `external_link_evidence` | 748 |
| `identity_resolution_case` | 348 |
| `projection_event_log` | 1 |

## Core compat 快照计数

| Compat table | Count |
| --- | ---: |
| `compat_canonical_subject` | 82878 |
| `compat_dj_profile` | 53555 |
| `compat_search_document` | 590927 |
| `compat_dj_org_rollup` | 323335 |
| `compat_graph_window_cache` | 53555 |
| `compat_activity_event_detail` | 196 |
| `compat_activity_evidence_ref` | 2181 |

这些 compat 快照不是 schema 美观优先，而是为了保护旧脚本、旧 API、旧 rank、旧 source count、旧 graph/org rollup 不回退。

## Serving 导出 readback

| Table | Count |
| --- | ---: |
| `canonical_subject` | 82878 |
| `dj_profile` | 53555 |
| `performance_event` | 508049 |
| `dj_event` | 1285827 |
| `dj_relation_rollup` | 701396 |
| `dj_venue_rollup` | 161810 |
| `evidence_ref` | 130591 |
| `graph_window_cache` | 53555 |
| `search_document` | 590927 |
| `activity_event_detail` | 508049 |
| `activity_evidence_ref` | 510034 |

FTS 状态：

- `search_document_fts` tokenizer：`trigram`
- unicode61 companion tokenizer：`unicode61`
- `OIL` old/new search count 在诊断中一致；中文城市搜索由 unicode61 companion 覆盖。

## Miniapp 导出 readback

| Table | Count |
| --- | ---: |
| `subject` | 82878 |
| `dj_profile` | 53555 |
| `dj_event` | 1285827 |
| `dj_collaborator` | 701396 |
| `dj_venue` | 145413 |
| `source_ref` | 130591 |
| `dj_identity_redirect` | 1668 |
| `dj_identity_profile_disposition` | 348 |

## Index readback

`atlas_index.json.gz` 保持 v4 shape：

| Key | Count |
| --- | ---: |
| `subjects` | 82878 |
| `profiles` | 53555 |
| `events` | 53555 |
| `collabs` | 46939 |
| `dj_venues` | 47162 |
| `source_refs` | 130591 |

## Identity gate

当前仍是 report-only：

| Field | Count |
| --- | ---: |
| `identity_resolution_case` | 348 |
| source-backed first lane | 38 |
| manual review required | 310 |
| external evidence required | 217 |
| `approved_for_s232d4_count` | 0 |
| `db_write_allowed_now_count` | 0 |

验收要求：DeepSeekTUI 只能为 38 source-backed cases 生成 approval packet 草稿，310 行不足证据的仍 pending，不得进入 S232D-4。

## 安全验收

`atlas_core_safe_execution_report.json`：

- `decision=atlas_core_safe_execution_passed`
- `blockers=[]`
- `report_local_output_only=true`
- `production_db_write_executed=false`
- `source_db_write_executed=false`
- `source_hash_guard_enforced=true`
- `source_hashes_unchanged=true`

## Shadow/API 验收

`atlas_core_api_shadow_diff_summary.md`：

- compared paths：20
- regression findings：0
- leak findings：0
- exact summary hash match：15
- source hashes unchanged：true

覆盖路径包括：

- health/manifest/overview
- DJ/entity search：MaFoL、DaRou、OIL、Loopy、DJ
- city/event search：深圳、上海
- mobile API：Loopy、OIL
- profile detail：MaFoL、DaRou
- graph seed：MaFoL、Loopy
- Atlas web page、Atlas graph page
- activity event detail
- source evidence lookup

## Source hash guard

本轮确认的 source hashes：

| Source | SHA256 |
| --- | --- |
| DB1 | `0fbb77fd8b70e5c3591751625d4befd4487bc376a08b30b71f12e2874d136cab` |
| DB2 | `fc6f565e28a04a142afad140c5f0b8634e07cc8a5002d74f00994c898fe812fe` |
| DB3 | `0b9e580e1e0fa0a85aec10525db9646f14a1593cbccc7a0a4d798f90014fcda1` |
| S119 sidecar | `2dba9308acde15b7c3b0af89562b4394e685639a8d307274b2630d6c27314934` |
| S232D3B8 | `5c05413a98faeb41d3e642aa7e1907dc15c73674a8c3dfaa0dd4d8fdb2bbc997` |

## 验收边界

这次验收只允许说：

```text
Atlas Core report-local candidate is ready for further shadow read and DeepSeekTUI optimization.
```

不能说：

```text
Atlas Core is production ready.
DB3 identity merge is approved.
Miniapp release is ready.
Production DB pointer can be switched.
```
