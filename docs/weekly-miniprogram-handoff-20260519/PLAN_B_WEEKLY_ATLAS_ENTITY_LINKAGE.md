# 计划二：周活小程序 × 电子音乐图谱实体联动

Updated: 2026-05-19  
Status: **设计稿**（未实施）  
Note: 图谱 **生产写入** 不在周活线程；本计划定义 **契约与解析层**。

## 1. 分工哲学

| | 周活小程序 | 电子音乐图谱 |
|--|-----------|--------------|
| 时间 | 未来 15 天 | 4.7 万+ 历史 |
| 产品 | 大众查活动 | 图谱/RAG/研究 |
| 实体 | 活动级快照 | canonical 艺人/场地/关系 |
| 准确率 | 展示极严 | candidate + review 分层 |

**联动原则**

1. 图谱负责「是谁」（ID、别名、verified bio、资产）
2. 周活负责「这一场」（日期、本场 lineup 证据）
3. 周活 **不** 重复跑 full 图谱抽取；做 **Entity Linking**

## 2. 架构

```
周活: OCR+LLM → lineup 字符串 + evidence
图谱: Artist/Venue/Event 节点 + 别名
联动: Entity Resolver → Confidence Merge → Weekly Entity Snapshot → 小程序 enriched
```

## 3. 图谱可提供（下行）

| 能力 | 小程序用法 |
|------|------------|
| 艺人消歧 | canonical_name |
| Verified bio | 艺人页简介（仅 verified） |
| DJ 图片 | 头像/海报（带 source image_id） |
| 场地 | 地址、同馆历史（可选深度） |

**禁止灌入**

- 未验证图谱边、向量猜同台、历史 lineup 猜本场

## 4. Entity Resolver

### 输出示例

```yaml
lineup_resolved:
  - raw: "Doon Kanda"
    artist_id: "atlas:entity:xxxx" | null
    match_score: 0.91
    match_method: alias_exact | fuzzy | vector_candidate
    verified: true
```

### 匹配阶梯

| 阶 | 方法 | 自动采纳 |
|----|------|----------|
| 1 | registry seed exact | 是 |
| 2 | 图谱 alias exact | ≥0.98 |
| 3 | fuzzy 唯一候选 | ≥0.92 |
| 4 | 向量 top-1 | **否**，仅 review |
| 5 | 无匹配 | 保留 raw，不伪造 ID |

## 5. 数据契约

### 周活 → 图谱（上行，低频）

- 每周 publish 后：`weekly_entity_observations.jsonl`（lineup/venue/evidence/url_hash）
- 图谱 ingest 为 observation，**不**直接改 production

### 图谱 → 周活（下行）

- API 物化前：`enrich_weekly_from_atlas_resolver`（概念脚本）
- 写入 `artist_profiles[]`：**仅 verified**
- **不增加** 无 evidence 的 lineup 人名

## 6. 图谱侧全量实体（图谱线程）

| 阶段 | 图谱工作 | 周活获益 |
|------|----------|----------|
| G0 | 统一 schema + 别名导出 | resolver 有料 |
| G1 | 47k batch → candidate 表 | 别名召回 |
| G2 | 500 高频 DJ verified | bio/图 |
| G3 | verified 关系边 | 深度页 |
| G4 | 实体 API（非向量搜人进周活） | 消歧助手 |

## 7. 路线图

| 阶段 | 周期 | 交付 |
|------|------|------|
| L0 契约 | 2 周 | WeeklyAtlasEntityContract.md |
| L1 Resolver v0 | 4 周 | exact + fuzzy snapshot |
| L2 小程序读 snapshot | 3 周 | 艺人页 artist_id |
| L3 Observation 上行 | 4 周 | 每周 observation 导出 |
| L4 向量候选 review | 6 周 | 仅人工，不进自动展示 |

## 8. 与计划一协同

- 计划一 P0 golden 标注 `artist_id` → 计划二 L1 评测
- 计划一 P3 verified bio ← 计划二 L1
- 计划一提升 lineup 召回；计划二只做 **标准化**，不猜阵容

## 9. 风险决策（待用户拍板）

| 决策 | 推荐 |
|------|------|
| bio 展示 | 仅 verified |
| 向量自动匹配 | 不用 |
| OCR 成本 | 风险行优先，渐进全量 |
| 代码边界 | 独立 `weekly_atlas_bridge` 模块 |
