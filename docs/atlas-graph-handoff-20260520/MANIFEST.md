# 图鉴 / 知识图谱接手包 — 文档索引 (MANIFEST.md)

**文件状态**: 接手导航索引；当前线程 SSOT 为 `docs/ATLAS_SOCIAL_SEARCH_RULES_SSOT_20260521.md`  
**更新日期**: 2026-05-21  
**项目根目录**: `C:\code\githubstar\wechathtmldownload`  
**关联线程**: 中国地下电子音乐图鉴 — 关系网络/知识图谱与多板块联动

---

## 1. 下一位 Agent 读序（强制）

| 顺序 | 文档 | 格式 | 用途 |
|---:|---|---|---|
| **1** | `docs/ATLAS_SOCIAL_SEARCH_RULES_SSOT_20260521.md` | MD | **当前线程 SSOT** — Atlas 后半段社交媒体搜索算法、规则、门禁与文档统一口径 |
| **2** | `NEXT_AGENT_HANDOFF_ATLAS_GRAPH_20260521.md` | MD + HTML | 混合主接手入口；本线程只取 Atlas social-search 部分 |
| **3** | `reports/ATLAS_POST_OPEN_SOURCE_SEARCH_PLAN_20260521.md` | MD + HTML | **【新专属计划 1】图谱后期开源搜索计划** — 五工具栈、SearXNG 优化与后过滤隔离；现为 SSOT 输入文档 |
| **4** | `reports/WEEKLY_MINIPROGRAM_AND_CLOUDRUN_PLAN_20260521.md` | MD + HTML | **【新专属计划 2】小程序与 CloudRun/CloudBase 计划** — 当前线程外；保留为混合历史入口 |
| **5** | `reports/NEW_AGENT_QUANT_FINAGENT_PLAN_20260521.md` | MD + HTML | **【新专属计划 3】NewAgent 金融量化与 FinAgent 计划** — 当前线程外；保留为混合历史入口 |
| **6** | `docs/ELECTRONIC_MUSIC_GRAPH_CURRENT_AUTHORITY_20260518.md` | MD | 生产数据基线与权威 (138,102 篇章/875k 图实体) |
| **7** | `reports/ATLAS_OPEN_SOURCE_RESEARCH_STACK_SUPER_PLAN_20260520.md` | MD + HTML | 历史开源栈底层框架规约 (Qiaomu/OpenCLI/Camofox/Maigret) |
| **8** | `docs/ELECTRONIC_MUSIC_GRAPH_PIPELINE_STAGE_MAP_20260518.md` | MD | 十阶段代码地图与脚本关系映射 |

可视化导航：请打开当前文件夹下的 **`INDEX.html`**。

---

## 2. 线程边界规约

| 线程名称 | 包含内容 (In-Scope) | 拒绝重叠 (Out-of-Scope) | 关键安全红线 |
|---|---|---|---|
| **1. Atlas 图谱后期** | 138k 基线、1024-d 向量、246k 实体后过滤与 Adjudication、五工具 OSINT。 | 生产 Neo4j / Qdrant 写入。 | **accepted_edges 保持 0 字节**，禁止无授权写入。 |
| **2. 小程序与 CloudRun** | CloudBase P0 级运维续费、CloudRun us-central1 部署、v0.4.0 上传提审、前端渲染优化。 | 跨仓库金融任务、全量图谱构建。 | 部署前必过 `check_weekly_release_guard.ps1`。 |
| **3. 金融量化与 FinAgent**| 500+ A 股监控、AKShare 平替、DeepSeek-v4 情感门禁、md5 翻译缓存、PC Fluent 密集重塑。 | 微信小程序 SDK、图谱向量重合。 | 保持工作路径隔离在 `daily_stock_analysis` 中运行。 |

---

## 3. 当前生产数据快照 (2026-05-21)

* **Stable articles**: `138,102` (整合 V6 完整 LLM 基线)
* **Graph entities / events**: `913,082 / 158,490` (Neo4j Staging 验证)
* **Release entities / events**: `1,510,787 / 608,678` (API 静态 Manifest)
* **External identity accepted edges**: `0` (严格保持空)
* **Qdrant role aliases**: `11` (已 apply 运行正常)
* **Verify**: `stage7_safe_handoff_verify.ps1` **PASS (100% 离线绿色安全)**

---

## 4. 推荐给下一位 Agent 的启动命令

```powershell
powershell -ExecutionPolicy Bypass -File C:\code\githubstar\wechathtmldownload\tools\stage7_rewrite\scripts\stage7_safe_handoff_verify.ps1
```
*(一键拉起安全沙箱，全量通过 Python 和 CloudRun API 本地测试，无远程写风险。)*
