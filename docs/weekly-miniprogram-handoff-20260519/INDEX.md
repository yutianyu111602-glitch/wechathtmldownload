# HUAIDJ 周活小程序 — 接手文档包索引



Updated: 2026-05-21

Scope: **仅周活小程序线**（不含电子音乐图鉴主线实现，但计划二描述图谱联动边界）



## ⭐ 统一主计划（唯一执行入口）



| 文件 | 用途 |

|------|------|

| **[PLAN_WEEKLY_MINIPROGRAM_UNIFIED.md](./PLAN_WEEKLY_MINIPROGRAM_UNIFIED.md)** | **全文合一**：Phase II Sprint、RA/Atlas/去重/IA/UI、管线 Task、门禁、DoD |
| **[HANDOFF_CHECKPOINT_20260519.md](./HANDOFF_CHECKPOINT_20260519.md)** | **当前事实快照**：数字、已完成 Sprint、下一步 |
| **[DOC_CODE_PLAN_SYNC_AUDIT_20260521.md](./DOC_CODE_PLAN_SYNC_AUDIT_20260521.md)** | **文档生命周期/代码事实审计**：权威、历史、归档分层 |
| **[DEDUP_SOURCE_INTEGRATION_LOGIC_20260521.md](./DEDUP_SOURCE_INTEGRATION_LOGIC_20260521.md)** | **去重算法与推文来源整合 SSOT**：不重复发卡、不丢来源 |
| **[SPRINT3_CLUB_SOURCE_CLOSEOUT_20260521.md](./SPRINT3_CLUB_SOURCE_CLOSEOUT_20260521.md)** | **Sprint 3 本地闭环**：Club Profile、source articles、organizer_key、routing/pagination |



以下 PLAN_* 已并入上文，**勿再当作执行入口**：`PLAN_MINIPROGRAM_NEXT_PHASE` · `PLAN_HV_ATLAS_RA_UI` · `PLAN_DEDUP_LOGIC_RA` · `PLAN_IA_SCHEDULE` · `PLAN_MASTER_INTEGRATED` · `PLAN_B_VECTOR_ATLAS_EXECUTION`



---



## 权威事实（当前）



| 项 | 值 |

|----|-----|

| CloudRun | `weekly-api-039`（以 `apps\weekly_activity_miniprogram\OPENCLAW_AUTOMATION.md` 顶部为准） |
| 发布条数 | 158 |
| 窗口 | `2026-05-20..2026-06-03` |
| 小程序开发版 | `2026.05.21.1`（既有开发版；本线程未新上传；未提审） |
| API 包 | `D:\downstream_results\stage7_rewrite\longrun\WEEKLY_ACTIVITY_MINIPROGRAM_API_20260520` |
| OpenClaw 入口 | `tools\stage7_rewrite\run_openclaw_weekly_daily_publish.ps1` |
| 本次 guardian 复验 | 本地 URL/source/158/mini tests 过；整体 `ok=false`，公网 API probe 超时且 daily queue exporter refresh 无有效行 |



| 本地全做收口 | `reports\ATLAS_WEEKLY_ALL_DO_CLOSEOUT_20260521.md`；含 Atlas 只读 detail 接口、本地 review/Golden/ingest/release dry-run 包 |

历史数量 `28/51/57/74/100/103/104/107/151/167/173` 等 **不得** 当作当前线上事实。


---



## 文档清单



### 运维与状态（独立维护）



| 文件 | 用途 |

|------|------|

| [HANDOFF_CHECKPOINT_20260519.md](./HANDOFF_CHECKPOINT_20260519.md) | **检查点**（一页续跑，Sprint 末更新数字） |

| [DOC_CODE_PLAN_SYNC_AUDIT_20260521.md](./DOC_CODE_PLAN_SYNC_AUDIT_20260521.md) | **文档/代码/计划生命周期审计** |

| [DEDUP_SOURCE_INTEGRATION_LOGIC_20260521.md](./DEDUP_SOURCE_INTEGRATION_LOGIC_20260521.md) | **当前去重与推文来源整合逻辑** |

| [SPRINT3_CLUB_SOURCE_CLOSEOUT_20260521.md](./SPRINT3_CLUB_SOURCE_CLOSEOUT_20260521.md) | **Club/source local closeout** |

| [NEXT_AGENT_HANDOFF_WEEKLY_MINIPROGRAM_FULL.md](./NEXT_AGENT_HANDOFF_WEEKLY_MINIPROGRAM_FULL.md) | 2026-05-19 长版接手；**历史证据，当前数字看 CHECKPOINT** |

| [P0_EXECUTION_STATUS_20260519.md](./P0_EXECUTION_STATUS_20260519.md) | P0 执行状态 |

| [P0_BASELINE_REPORT_20260519.md](./P0_BASELINE_REPORT_20260519.md) | P0 baseline 报告 |

| [WeeklyAtlasEntityContract.md](./WeeklyAtlasEntityContract.md) | L0 契约全文（UNIFIED §8 为摘要） |



### 深度研究原文（归档，已摘要入 UNIFIED）



| 文件 | 用途 |

|------|------|

| [PLAN_A_DEEPRESEARCH_v2.md](./PLAN_A_DEEPRESEARCH_v2.md) | 计划一 LDR 强化稿 |

| [PLAN_B_DEEPRESEARCH_v2.md](./PLAN_B_DEEPRESEARCH_v2.md) | 计划二 LDR 强化稿 |

| [PLAN_A_WEEKLY_RECOGNITION_ACCURACY.md](./PLAN_A_WEEKLY_RECOGNITION_ACCURACY.md) | 计划一 v1 概要 |

| [PLAN_B_WEEKLY_ATLAS_ENTITY_LINKAGE.md](./PLAN_B_WEEKLY_ATLAS_ENTITY_LINKAGE.md) | 计划二 v1 概要 |

| [DEEPRESEARCH_RUN_20260519.md](./DEEPRESEARCH_RUN_20260519.md) | LDR 运行记录 |

| [archive/ARCHIVE_INDEX_20260519.md](./archive/ARCHIVE_INDEX_20260519.md) | 档案总索引 |



### 已合并计划（仅 diff/历史参考）



| 文件 | 并入 UNIFIED 章节 |

|------|------------------|

| [PLAN_MINIPROGRAM_NEXT_PHASE_20260521.md](./PLAN_MINIPROGRAM_NEXT_PHASE_20260521.md) | §9–11 |

| [PLAN_HV_ATLAS_RA_UI_INTEGRATED_20260520.md](./PLAN_HV_ATLAS_RA_UI_INTEGRATED_20260520.md) | §2–5、§8 |

| [PLAN_DEDUP_LOGIC_RA_20260520.md](./PLAN_DEDUP_LOGIC_RA_20260520.md) | §7 |

| [PLAN_IA_SCHEDULE_PLACEMENT_20260520.md](./PLAN_IA_SCHEDULE_PLACEMENT_20260520.md) | §6 |

| [PLAN_MASTER_INTEGRATED_20260520.md](./PLAN_MASTER_INTEGRATED_20260520.md) | §10 |

| [PLAN_B_VECTOR_ATLAS_EXECUTION_20260519.md](./PLAN_B_VECTOR_ATLAS_EXECUTION_20260519.md) | §8 |

| [PLAN_ROADMAP_20260519.md](./PLAN_ROADMAP_20260519.md) | §10.3 |



### 交付物与其它



| 文件 | 用途 |

|------|------|

| [DELIVERABLE_URL_TRACE_51.md](./DELIVERABLE_URL_TRACE_51.md) | 51 条 URL 溯源 |

| [DELIVERABLE_OPENCLAW_OBSERVATION_CHECKLIST.md](./DELIVERABLE_OPENCLAW_OBSERVATION_CHECKLIST.md) | OpenClaw 观测清单 |

| [DELIVERABLE_CODE_DOC_AUDIT.md](./DELIVERABLE_CODE_DOC_AUDIT.md) | 代码与文档审计 |

| [MEMORY_SYNC_20260519.md](./MEMORY_SYNC_20260519.md) | mem0 / agentmemory 同步 |

| [html/MASTER_DASHBOARD.html](./html/MASTER_DASHBOARD.html) | 可视化总览 |

| [html/](./html/) | Markdown HTML 伴生页 |

| `../../reports/ATLAS_WEEKLY_ALL_DO_CLOSEOUT_20260521.md` | **2026-05-21 全做收口**：本地 Atlas 只读联动、review 包、Golden 包、observations ingest dry-run、release dry-run 与门禁证据 |

| `../../reports/WEEKLY_EXPORTER_REFRESH_GATE_HARDENING_20260521.md` | **2026-05-21 续跑硬化**：Release Guardian 改为 exporter refresh effective 门禁；当前因 `0/122` 成功账号、`ret=200003 invalid session` 而正确阻断 |


---



## 外部权威（仓库内）



- `NEXT_AGENT_HANDOFF_20260519_OPENCLAW_DAILY_RELEASE.md`

- `tools\stage7_rewrite\OPENCLAW_WEEKLY_DAILY_UPDATE_RUNBOOK.md`

- `apps\weekly_activity_miniprogram\OPENCLAW_AUTOMATION.md`

- `docs\WEEKLY_ACTIVITY_PUBLISHED_SCHEMA_V1_2026-05-08.md`

- `reports/ATLAS_WEEKLY_INTEGRATED_UNDERSTANDING_20260520.md`（Atlas 主线）



---



## 下一 agent 阅读顺序



1. 本 INDEX

2. `HANDOFF_CHECKPOINT_20260519.md`

3. **`PLAN_WEEKLY_MINIPROGRAM_UNIFIED.md`**

4. `DEDUP_SOURCE_INTEGRATION_LOGIC_20260521.md`

5. `SPRINT3_CLUB_SOURCE_CLOSEOUT_20260521.md`

6. `OPENCLAW_AUTOMATION.md` 顶部

7. 按需：`DELIVERABLE_*` · `PLAN_A/B_DEEPRESEARCH_v2` · `html/MASTER_DASHBOARD.html`



---



## HTML 生成



```powershell

$dir = "C:\code\githubstar\wechathtmldownload\docs\weekly-miniprogram-handoff-20260519"

$renderer = "C:\Users\pc\.codex\skills\html-handoff-summary\scripts\render_handoff_html.py"

python $renderer (Join-Path $dir "PLAN_WEEKLY_MINIPROGRAM_UNIFIED.md") -o (Join-Path $dir "html/PLAN_WEEKLY_MINIPROGRAM_UNIFIED.html") --kind handoff

Get-ChildItem $dir -Filter "*.md" | Where-Object { $_.Name -notin @("INDEX.md") } | ForEach-Object {

  python $renderer $_.FullName -o (Join-Path $dir "html" ($_.BaseName + ".html")) --kind handoff

}

```
