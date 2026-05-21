# NEXT AGENT HANDOFF — HUAIDJ 周活小程序（完整接手）

> Lifecycle: HISTORICAL_EVIDENCE. This is the 2026-05-19 long-form handoff. Current execution truth is `HANDOFF_CHECKPOINT_20260519.md` + `PLAN_WEEKLY_MINIPROGRAM_UNIFIED.md` + `DOC_CODE_PLAN_SYNC_AUDIT_20260521.md`. Do not use the 103-item / backendRawHits=51 values below as current runtime facts.

Generated: 2026-05-19（续跑版，含 P0 度量 + 向量图谱桥接 L1）
Agent session: 周活专项 + 计划一 P0 + 计划二 L1
Repo path: `C:\code\githubstar\wechathtmldownload`（**非 Git 根**）

## 1. Main Problem

周活已稳定发布（`weekly-api-033` / 103 条），但 **识别准确率**（空 lineup、保守 repair）与 **后端 51 处 URL 行** 仍待改进；**实体联动**已具备只读桥接（`weekly_atlas_bridge`），但图谱 alias 导出未接入，当前匹配几乎全为 `no_match`。下一 agent 应在 **0 hard_fail 发布门** 下推进人工 Golden 标注、P1 URL 清洗（需批准）、计划二 L2 snapshot 挂载。

## 2. Scope

### In scope

- `apps\weekly_activity_miniprogram\`
- `services\weekly_activity_cloudrun\` → `/api/v1/weekly/*`
- `tools\stage7_rewrite\` 周活管线 + **P0 Golden** + **`weekly_atlas_bridge`**
- OpenClaw `run_openclaw_weekly_daily_publish.ps1` + release guardian
- 接手包 `docs\weekly-miniprogram-handoff-20260519\`

### Out of scope（除非用户明确要求）

- 电子音乐图鉴 93k/47k、Neo4j/Qdrant **生产写入**、Next1000
- 微信提审
- 无界 `D:\` 扫描、读取 secret

## 3. Thread Boundary（用户明确要求）

**小程序是小程序，图谱是图谱。** 本线程只改周活侧；图谱仅通过 **只读 snapshot / observation 上行** 联动。向量命中 **不得** 自动进小程序 lineup 展示。

## 4. Current Reality

### Confirmed（2026-05-19）

| 层 | 状态 |
|----|------|
| 远端后端 | `weekly-api-033`，103 条，reconcile 103/103 |
| 发布窗口 | `2026-05-19..2026-06-02` |
| 本地 API 包 | `D:\downstream_results\stage7_rewrite\longrun\WEEKLY_ACTIVITY_MINIPROGRAM_API_20260519` |
| 小程序开发版 | `2026.05.19.8`（已上传，**未提审**） |
| release guardian | ok=true；visibleHits=0；**backendRawHits=51** |
| lineup 覆盖 | ~40/103 有 lineup；audit missing_lineup **63/103** |
| 小程序单测 | **24/24** pass |
| P0 Golden 种子 | **88** 条，`annotation_status: pending`（0 verified） |
| P0 脚本 + 单测 | bootstrap / evaluate / `weekly_golden_lib`；**4/4** pass |
| 计划二 L0 契约 | `WeeklyAtlasEntityContract.md` |
| 计划二 L1 bridge | `tools/stage7_rewrite/weekly_atlas_bridge/`；resolver 单测 **4/4** pass |
| snapshot dry-run | `weekly_entity_snapshot.json`（89 lineup 行，全 `no_match` — seed 过小） |
| observation dry-run | `weekly_entity_observations.jsonl`（103 行） |
| LDR 深度研究 | 已落盘 `archive/`（候选，**HOLD**，非已实施） |

### Hypotheses

- lineup 空 = 保守 repair + OCR 覆盖 + 日期窗漏斗，不单是 LLM
- `no_match` 89/89 主因：**registry seed 仅少量艺人**，待图谱 `atlas_alias_export.jsonl`（G0）
- Linux cron 可能仍跑旧脚本，未必已切 Windows OpenClaw wrapper

### Unverified

- 真机全面 smoke
- 微信审核状态
- OpenClaw **定时首跑**观测
- Qdrant `person_current` 向量 review（需本机 6333 + `--enable-vector-review`）

## 5. Work Performed（截至本接手）

| 类别 | 内容 |
|------|------|
| 文档 | 计划一/二 v1+v2、LDR 档案、`PLAN_ROADMAP`、`PLAN_B_VECTOR_ATLAS_EXECUTION` |
| P0 代码 | `bootstrap_weekly_golden_set.py`、`evaluate_weekly_golden_baseline.py`、`weekly_golden_lib.py` |
| P0 数据 | `golden_set_v1.jsonl`（88）、`golden_baseline_20260519` 报告 |
| 计划二 L1 | `weekly_atlas_bridge`（resolver/indexes/snapshot/observations）+ CLI 脚本 |
| 产物 | 当前包下 `weekly_entity_snapshot.json`、`weekly_entity_observations.jsonl` |
| 业务代码 | **未改** build/repair/CloudRun/小程序发布逻辑 |

## 6. Verification Status

| 检查 | 结果 |
|------|------|
| release guardian @ 20260519 | ok |
| node --test 小程序 | 24 pass |
| unittest golden baseline | 4 pass |
| unittest atlas bridge | 4 pass |
| snapshot/observation 生成 | 成功（见上表） |
| 人工 Golden verified | **未做** 0/88 |
| P1 build URL 清洗 | **未实施**（需用户批准） |
| DevTools E2E | 未跑 |

## 7. Current Blockers

| ID | 阻塞 | 解阻条件 |
|----|------|----------|
| B1 | Golden 全 pending | 人工标注 ≥20 条 `verified` 后重跑 baseline |
| B2 | 实体匹配无召回 | 图谱侧 G0 导出 `atlas_alias_export.jsonl` 或扩充 registry |
| B3 | backendRawHits=51 | P1 改 `build_weekly_activity_miniprogram_api.py` + 用户批准 |
| B4 | OpenClaw cron | 首跑日志/观测清单 |

## 8. Next Best Entry

### 第一步（只读，5 分钟）

1. 读 `docs\weekly-miniprogram-handoff-20260519\INDEX.md`
2. 读 `PLAN_ROADMAP_20260519.md`
3. 跑 guardian：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File C:\Users\pc\.codex\skills\huaidj-weekly-release-guardian\scripts\check_weekly_release_guard.ps1 -CurrentReleaseDir D:\downstream_results\stage7_rewrite\longrun\WEEKLY_ACTIVITY_MINIPROGRAM_API_20260519
```

### 第二步（按优先级）

| 优先级 | 动作 | 参考 |
|--------|------|------|
| P0 | 人工标注 Golden → `verified` → `evaluate_weekly_golden_baseline.py` | `P0_BASELINE_REPORT_20260519.md` |
| P0 | OpenClaw 首跑观测 | `DELIVERABLE_OPENCLAW_OBSERVATION_CHECKLIST.md` |
| P1 | URL 清洗（**先获用户批准**） | `DELIVERABLE_URL_TRACE_51.md` |
| L2 | build 前挂载 snapshot；传入 `--alias-export` | `PLAN_B_VECTOR_ATLAS_EXECUTION_20260519.md` |
| L2+ | Qdrant 向量 review（只读，不进展示） | `--enable-vector-review` |

### 计划二 CLI（已可用）

```powershell
cd C:\code\githubstar\wechathtmldownload

python tools\stage7_rewrite\scripts\build_weekly_atlas_snapshot.py `
  --current D:\downstream_results\stage7_rewrite\longrun\WEEKLY_ACTIVITY_MINIPROGRAM_API_20260519\current.json `
  --out D:\downstream_results\stage7_rewrite\longrun\WEEKLY_ACTIVITY_MINIPROGRAM_API_20260519\weekly_entity_snapshot.json `
  --publish-package WEEKLY_ACTIVITY_MINIPROGRAM_API_20260519

python tools\stage7_rewrite\scripts\export_weekly_entity_observations.py `
  --current D:\downstream_results\stage7_rewrite\longrun\WEEKLY_ACTIVITY_MINIPROGRAM_API_20260519\current.json `
  --out D:\downstream_results\stage7_rewrite\longrun\WEEKLY_ACTIVITY_MINIPROGRAM_API_20260519\weekly_entity_observations.jsonl `
  --window-start 2026-05-19 --window-end 2026-06-02
```

## 9. Key Code Map

| 路径 | 职责 |
|------|------|
| `apps\weekly_activity_miniprogram\utils\format.js` | 展示契约、URL 过滤 |
| `scripts\archive_old\build_weekly_activity_miniprogram_api.py` | 物化 current（**dj_bio_lines 恒 []**） |
| `scripts\bootstrap_weekly_golden_set.py` | Golden 种子 |
| `scripts\evaluate_weekly_golden_baseline.py` | P0 baseline |
| `weekly_atlas_bridge\resolver.py` | 实体五级匹配 |
| `scripts\build_weekly_atlas_snapshot.py` | snapshot 导出 |
| `registries\weekly_artists_seed.json` | 艺人 registry seed |

## 10. Warnings / Pitfalls

- 勿把图鉴 47k/Neo4j 进度当作周活条数
- 勿用历史条数 28/51/57/74/100/104/107 当线上事实
- `missing_lineup` 不是 hard_fail；提召回需 Golden，不能单放宽 audit
- `vector_candidate` **禁止** `display_tier=show`
- snapshot 当前全 `no_match` **不是** resolver 坏了，是 **alias 数据未接入**
- 未获批准勿改 build/repair/deploy

## 11. Related Artifacts

| 路径 | 说明 |
|------|------|
| `docs\weekly-miniprogram-handoff-20260519\INDEX.md` | 文档索引 |
| `PLAN_A_DEEPRESEARCH_v2.md` / `PLAN_B_DEEPRESEARCH_v2.md` | 深度研究强化稿 |
| `PLAN_B_VECTOR_ATLAS_EXECUTION_20260519.md` | 向量×图谱可执行计划 |
| `P0_EXECUTION_STATUS_20260519.md` | P0 状态 |
| `archive\ARCHIVE_INDEX_20260519.md` | LDR/DeepSeek/P0 档案 |
| `...\weekly_entity_snapshot.json` | 实体 snapshot（dry-run） |
| `...\weekly_entity_observations.jsonl` | 图谱上行 observation |
| `D:\downstream_results\golden\golden_set_v1.jsonl` | Golden 主本 |

## 12. HTML Companion

- 路径：`docs\weekly-miniprogram-handoff-20260519\html\NEXT_AGENT_HANDOFF_WEEKLY_MINIPROGRAM_FULL.html`
- 生成：见 `INDEX.md` § HTML 生成

## 13. OpenHuman Import

- imported: **no**（本会话未执行 OpenHuman）
- 原因：环境未配置或未请求导入
