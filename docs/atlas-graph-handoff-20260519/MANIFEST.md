# 图鉴 / 知识图谱接手包 — 文档索引

Updated: 2026-05-19  
Project: `C:\code\githubstar\wechathtmldownload`  
Thread: **中国地下电子音乐图鉴** — 关系网络 / 知识图谱（**非** weekly 小程序）

---

## 1. 下一位 Agent 读序（强制）

| 顺序 | 文档 | 格式 | 用途 |
|---:|---|---|---|
| 1 | `NEXT_AGENT_HANDOFF_ATLAS_GRAPH_20260519.md` | MD + HTML | **主接手入口** — 问题、范围、阻塞、下一步 |
| 2 | `reports/ATLAS_GRAPH_FULL_UNDERSTANDING_20260519.md` | MD + HTML | 图鉴主线全量理解 |
| 3 | `reports/ATLAS_KNOWLEDGE_GRAPH_MEGA_PLAN_20260519.md` | MD + HTML | 12 Epic 超级计划 + DB/脚本审计 |
| 3b | `reports/ATLAS_KNOWLEDGE_GRAPH_DEEP_RESEARCH_PLAN_20260519.md` | MD + HTML | **深化研究计划** — AC/DAG/风险/Sprint（DeepSeek v4-pro） |
| 4 | `docs/ELECTRONIC_MUSIC_GRAPH_CURRENT_AUTHORITY_20260518.md` | MD | 生产数字 SSOT |
| 5 | `docs/ELECTRONIC_MUSIC_GRAPH_PIPELINE_STAGE_MAP_20260518.md` | MD | 十阶段代码地图 |
| 6 | `docs/ELECTRONIC_MUSIC_ATLAS_FINAL_COMPLETION_PLAN_20260519.md` | MD | 收尾计划 |
| 7 | `tools/stage7_rewrite/STAGE7_GRAPH_CURRENT_AUTHORITY_20260518.md` | MD | Stage7 图相位权威 |

可视化导航：打开 **`INDEX.html`**（本目录）。

---

## 2. 本接手包产出文件清单

### 2.1 Markdown（canonical SSOT）

```
C:\code\githubstar\wechathtmldownload\
├── NEXT_AGENT_HANDOFF_ATLAS_GRAPH_20260519.md          ← 主 handoff
├── reports\
│   ├── ATLAS_GRAPH_FULL_UNDERSTANDING_20260519.md      ← 图鉴理解
│   ├── ATLAS_KNOWLEDGE_GRAPH_MEGA_PLAN_20260519.md     ← 超级计划
│   ├── ATLAS_KNOWLEDGE_GRAPH_DEEP_RESEARCH_PLAN_20260519.md  ← 深化研究（实施 AC）
│   └── PROJECT_FULL_UNDERSTANDING_20260519.md          ← 全项目（含 weekly，参考用）
└── docs\atlas-graph-handoff-20260519\
    └── MANIFEST.md                                     ← 本索引
```

### 2.2 HTML（human companion）

```
C:\code\githubstar\wechathtmldownload\
├── NEXT_AGENT_HANDOFF_ATLAS_GRAPH_20260519.html
├── reports\
│   ├── ATLAS_GRAPH_FULL_UNDERSTANDING_20260519.html
│   ├── ATLAS_KNOWLEDGE_GRAPH_MEGA_PLAN_20260519.html
│   └── ATLAS_KNOWLEDGE_GRAPH_DEEP_RESEARCH_PLAN_20260519.html
└── docs\atlas-graph-handoff-20260519\
    └── INDEX.html                                      ← 导航首页
```

---

## 3. 线程边界

| 属于本接手包 | 不属于（除非用户明确切换） |
|---|---|
| Neo4j / Qdrant / canonical registry / Graph RAG | weekly-api / 小程序 upload |
| stable_articles 47,470 / graph marker | OpenClaw daily publish runbook |
| Epic 0–11 mega plan | 103 条 weekly 发布真相 |
| Stage7 外部 identity evidence | WeChat 审核提交 |

---

## 4. 当前生产数字（快照）

**权威优先（2026-05-20）**：Stable **127,511** · Graph **875,368 / 150,752** · 见 `docs/ELECTRONIC_MUSIC_GRAPH_CURRENT_AUTHORITY_20260518.md`

Handoff 线程快照（2026-05-19）：

- Stable articles: **47,470**
- Graph entities / events: **316,481 / 59,932**
- External identity accepted edges: **0**
- Qdrant role aliases: **11** applied
- Pipeline readiness: `full_pipeline_ready`

数字权威源：`docs/ELECTRONIC_MUSIC_GRAPH_CURRENT_AUTHORITY_20260518.md`（若冲突以该文件为准）。

---

## 5. 推荐第一条命令

```powershell
powershell -ExecutionPolicy Bypass -File C:\code\githubstar\wechathtmldownload\tools\stage7_rewrite\scripts\stage7_safe_handoff_verify.ps1
```

---

## 6. 推荐第一条实现 Epic

**Epic 0** — Ontology 冻结 → **Epic 1** — Canonical Entity Registry

详见 `reports/ATLAS_KNOWLEDGE_GRAPH_DEEP_RESEARCH_PLAN_20260519.md` §5 Sprint 与 §12 Epic 0 清单；mega plan 第七节为 Epic 叙述原文。

---

## 7. 历史 handoff（勿与本包混淆）

| 文件 | 线程 |
|---|---|
| `NEXT_AGENT_HANDOFF_20260519_OPENCLAW_DAILY_RELEASE.md` | weekly OpenClaw |
| `NEXT_AGENT_HANDOFF_20260519.md` | weekly 综合 |
| `NEXT_AGENT_HANDOFF_20260517.md` | 历史 |

---

## 8. 维护规则

- 改计划 → 先改 MD，再重新 render HTML
- 新 Epic 开工 → 更新 handoff §7 Next Best Entry
- 生产数字变化 → 同步 `ELECTRONIC_MUSIC_GRAPH_CURRENT_AUTHORITY` + 本 MANIFEST §4
