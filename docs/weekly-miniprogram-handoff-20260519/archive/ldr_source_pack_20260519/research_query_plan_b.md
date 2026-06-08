# LDR 深度研究任务 — 计划二：周活 × 电子音乐图谱实体联动

角色：知识图谱工程师 + 实体解析架构师 + 周活小程序数据契约设计师。

## 硬约束（必须遵守）

1. **只根据 source_pack 内文件**回答；不得臆造 Neo4j/Qdrant 写入或图谱生产状态。
2. **线程边界**：小程序是小程序，图谱是图谱。本计划只定义**契约、Resolver、snapshot 下行、observation 上行**；**不在此线程**展开 93k/47k 图鉴管线实现或 production 图写入。
3. 联动原则：图谱管「是谁」，周活管「这一场」；**向量匹配不得自动进小程序展示**。
4. bio/头像仅 **verified** 或 registry `bio_manual`；无 evidence 不得增加 lineup 人名。
5. 输出为 **candidate research**，HOLD_FOR_HERMES_DECISION。

## 研究目标

在现有 `PLAN_B_WEEKLY_ATLAS_ENTITY_LINKAGE.md` 基础上，产出强化版 v2：

1. **WeeklyAtlasEntityContract** 草案：字段、版本号、兼容性、breaking change 策略
2. **Entity Resolver 规格**：五级匹配阶梯的阈值、冲突处理、多候选 UI 策略（hint 不展示 ID）
3. **Snapshot 物化格式**：`artist_profiles[]`, `lineup_resolved[]`, `venue_resolved` 示例 JSON
4. **上行 observation jsonl**：每周 publish 后字段、隐私/合规、图谱 ingest 边界（observation 不直写 production）
5. **分阶段 OKR（L0–L4）**：与计划一 P0–P3 的时间对齐表
6. **模块边界**：建议 `weekly_atlas_bridge` 目录结构、API 调用方式（只读 snapshot）
7. **评测**：resolver precision/recall 如何用计划一 golden 的 `artist_id` 字段评测
8. **风险决策表**：bio 展示、向量、OCR 成本、代码边界 — 给出推荐与备选

## 输出结构（Markdown）

1. 执行摘要
2. 分工与哲学（周活 vs 图谱）
3. 架构图（ASCII 或 mermaid）
4. 契约全文草案（核心 schema）
5. Resolver 算法规格（含伪代码）
6. 上下行数据格式示例
7. 分阶段 OKR + 与计划一协同矩阵
8. 模块/文件落地建议
9. 评测与观测指标
10. 待拍板决策（≤5 项）

请用**简体中文**撰写。
