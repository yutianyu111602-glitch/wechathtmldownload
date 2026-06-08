# Atlas 音乐关系图谱逻辑与全中文界面设计 - 2026-05-21

Status: design / implementation blueprint

目标：把 Atlas 做成面向中国地下/电子音乐场景的关系网络，而不是普通实体列表。用户搜一个场地、DJ、厂牌、活动或 mixtape 后，默认看到的是音乐生态关系：谁在哪里演过、未来去哪演、和谁经常同台、属于什么厂牌、发过什么作品、有哪些公开主页和证据来源。

## 参考轮子和技术依据

- [Cosmograph](https://cosmograph.app/) / [`cosmosgl/graph`](https://github.com/cosmosgl/graph): 大图 WebGL/GPU 渲染、社区级 Galaxy 模式参考。
- [Sigma.js](https://www.sigmajs.org/) / [Graphology data docs](https://www.sigmajs.org/docs/advanced/data/): WebGL 图渲染 + JS 图结构/算法生态，适合作为 2D/分析 fallback。
- [Meilisearch typo tolerance docs](https://www.meilisearch.com/docs/learn/relevancy/typo_tolerance_calculations): 拼写容错、别名、英文大小写和中英混搜参考。
- [Qdrant search docs](https://qdrant.tech/documentation/search/) / [Hybrid Queries](https://qdrant.tech/documentation/concepts/hybrid-queries/): 精确检索之外的语义召回、LLM 上下文检索和 dense/sparse hybrid 参考。

## 产品语义

Atlas 前台不是“所有数据都展示”，而是“围绕音乐问题展示最有用的一小片关系网络”。

默认用户问题：

- 搜场地：这个场地办过哪些活动、未来有什么活动、常出现哪些 DJ、和哪些厂牌/主办方关系强。
- 搜 DJ：这个 DJ 未来演出、历史演出、常去俱乐部、常合作对象、关联厂牌、mixtape/播客/现场录音、公开社交媒体。
- 搜厂牌：旗下/关联艺人、常合作场地、主办活动、作品发布、城市和社群边界。
- 搜活动：阵容、场地、主办/厂牌、相关历史活动、来源文章。
- 搜作品/mixtape：作者、发布平台、关联厂牌、关联活动或文章。

## 逻辑分类体系

采用类似达尔文生物分类的多级 taxonomy，但前台展示为中文短标签。

| 层级 | 字段 | 例子 | 作用 |
| --- | --- | --- | --- |
| 域 | `realm` | 音乐场景、证据来源、地理空间 | 粗分大世界，避免酒水/菜单/酒店推荐混入 |
| 界 | `kingdom` | 人与团体、空间、活动、作品、账号、文章 | 前台主要节点族群 |
| 门 | `phylum` | 艺人、组织、场地、演出、音频作品、社交主页 | 决定默认详情页结构 |
| 纲 | `class` | DJ、Producer、厂牌、Club、Festival、Mixtape | 决定图谱颜色和关系模板 |
| 目 | `order` | Techno、House、Bass、Ambient、Live set | 后续用于风格过滤 |
| 科 | `family` | 城市社群、厂牌网络、驻场网络 | 用于社区/星系分区 |
| 属 | `genus` | 同一厂牌/常驻场地/系列活动 | 用于关系聚合 |
| 种 | `species` | 具体身份类型组合 | 例如 DJ+Producer+LabelMember |
| 个体 | `individual` | MaFoL、DONG 洞、OIL、Do Hits | 用户直接搜索和点击的实体 |

前台中文节点族群：

- `人物 / DJ`
- `团体 / 厂牌`
- `空间 / 场地`
- `活动 / 演出`
- `作品 / Mixtape`
- `主页 / 社交媒体`
- `来源 / 文章`
- `城市 / 地点`

## 关系本体

边必须是音乐语义边，不再只靠“同一文章出现”。

| 关系 | 方向 | 证据来源 | 前台中文 |
| --- | --- | --- | --- |
| `EVENT_AT_VENUE` | 活动 -> 场地 | 活动 place/address/geocode | 活动地点 |
| `VENUE_HOSTED_EVENT` | 场地 -> 活动 | `EVENT_AT_VENUE` 反向聚合 | 举办活动 |
| `EVENT_HAS_PERFORMER` | 活动 -> DJ/艺人 | participants/lineup/OCR/文章 | 阵容 |
| `DJ_PLAYED_EVENT` | DJ -> 活动 | `EVENT_HAS_PERFORMER` 反向聚合 | 历史演出 |
| `DJ_FUTURE_EVENT` | DJ -> 未来活动 | weekly/current + 日期门禁 | 未来演出 |
| `DJ_AFFILIATED_LABEL` | DJ -> 厂牌/团体 | 简介、来源文章、社交主页交叉证据 | 关联厂牌 |
| `LABEL_HAS_ARTIST` | 厂牌 -> DJ | `DJ_AFFILIATED_LABEL` 反向聚合 | 关联艺人 |
| `LABEL_ORGANIZED_EVENT` | 厂牌/组织 -> 活动 | organizer/source account/title | 主办活动 |
| `DJ_RELEASED_WORK` | DJ -> 作品 | SoundCloud/Bandcamp/文章/外链 | 发布作品 |
| `WORK_ON_PLATFORM` | 作品 -> 平台主页 | 外链域名和页面证据 | 发布平台 |
| `DJ_HAS_SOCIAL_PROFILE` | DJ -> 公开主页 | 身份证据门禁后 | 公开主页 |
| `DJ_COLLAB_WITH` | DJ -> DJ | 同一活动、共同作品、同厂牌，按证据聚合 | 常合作 |
| `DJ_REGULAR_VENUE` | DJ -> 场地 | 历史演出频次/近期权重 | 常去场地 |
| `VENUE_REGULAR_DJ` | 场地 -> DJ | `DJ_REGULAR_VENUE` 反向聚合 | 常见 DJ |
| `SAME_SOURCE_CONTEXT` | 任意 -> 任意 | 同来源文章 | 上下文共现 |

`SAME_SOURCE_CONTEXT` 只能作为浅灰上下文边，不能代表合作、隶属、社交身份已确认。

## 查询镜头

### 搜场地

输入：`OIL`、`DADA`、`DONG 洞`、`TAG`。

默认镜头：`场地生态`

图谱结构：

```text
场地
  -> 未来活动
  -> 历史活动
      -> 演出 DJ
          -> 厂牌 / 团体
          -> 其他历史演出
  -> 常见 DJ
  -> 常合作主办 / 厂牌
  -> 城市 / 地址
  -> 来源文章
```

右侧详情：

- 场地身份卡：中文名、别名、城市、地址、公开主页、证据数。
- 未来活动：按日期排序，只显示当前/未来。
- 历史活动：最近 N 场和高置信经典活动。
- 常见 DJ：按 `venue_affinity_score` 排序。
- 关联厂牌/主办：按共同活动次数和近期权重排序。
- 来源证据：只列摘要和来源链接，不导出全文。

### 搜 DJ

输入：`MaFoL`、`Howie Lee`、`MIIIA`、`Difan`。

默认镜头：`DJ 履历`

图谱结构：

```text
DJ
  -> 未来演出
  -> 历史演出
      -> 场地
      -> 同台 DJ
      -> 主办 / 厂牌
  -> 常去俱乐部
  -> 常合作对象
  -> 厂牌 / collective
  -> mixtape / podcast / live set
      -> 发布平台
  -> 公开社交媒体
  -> 来源文章
```

右侧详情：

- 身份卡：中文/英文名、艺名、头像、城市、类型、置信度。
- 未来演出：日期、城市、场地、活动名。
- 历史演出：按时间倒序，聚合重复来源。
- 常去场地：显示次数、最近一次、代表活动。
- 常合作：按同台次数、共同厂牌、共同作品分组。
- 厂牌/组织：只展示证据达到门禁的关系。
- Mixtape/作品：标题、平台、发布时间、证据来源。
- 公开主页：只展示 accepted；candidate 单独标记候选。

### 搜厂牌

默认镜头：`厂牌网络`

```text
厂牌
  -> 关联艺人
  -> 主办活动
  -> 常合作场地
  -> 作品 / mixtape 系列
  -> 城市社群
  -> 公开主页
```

### 搜活动

默认镜头：`活动现场`

```text
活动
  -> 场地
  -> 阵容 DJ
  -> 主办 / 厂牌
  -> 相关文章
  -> 同系列活动
```

## 关系强度算法

所有强关系必须从 evidence 聚合而来。

### 常合作对象

```text
collab_score =
  2.0 * same_event_count
+ 1.5 * same_label_count
+ 1.2 * same_work_count
+ 0.8 * same_source_music_context_count
+ recency_bonus
+ source_diversity_bonus
- ambiguity_penalty
```

输出限制：

- 默认只返回前 `12` 个合作对象。
- 同一篇文章的重复提及只计一次。
- 只有同文共现、没有活动/作品/厂牌证据时，前台标为“上下文共现”，不标“合作”。

### 常去场地

```text
venue_affinity_score =
  2.5 * played_event_count
+ 1.0 * future_event_count
+ recency_bonus
+ city_match_bonus
+ source_diversity_bonus
- low_confidence_penalty
```

### 厂牌关联

```text
label_affinity_score =
  3.0 * explicit_label_member_evidence
+ 2.0 * organized_event_participation
+ 1.5 * shared_release_or_mixtape
+ 1.0 * official_social_crosslink
+ source_diversity_bonus
- candidate_only_penalty
```

### 作品/mixtape

`mixtape`、`podcast`、`radio show`、`live set` 先作为 `作品 / 音频作品` 节点，不要混入普通文章节点。作品节点必须有作者/平台/来源证据中的至少两项，或一个高可信官方平台链接。

## 服务端物化表

在 `atlas_serving.sqlite` 之外增加音乐关系读模型：

```sql
entity_music_profile(
  ceid TEXT PRIMARY KEY,
  display_name TEXT NOT NULL,
  primary_label_zh TEXT NOT NULL,
  subtitle_zh TEXT NOT NULL,
  summary_zh TEXT NOT NULL,
  avatar_url TEXT NOT NULL DEFAULT '',
  city TEXT,
  stats_json TEXT NOT NULL,
  relation_counts_json TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

music_relation_rollup(
  src_ceid TEXT NOT NULL,
  dst_ceid TEXT NOT NULL,
  rel_type TEXT NOT NULL,
  rel_label_zh TEXT NOT NULL,
  weight REAL NOT NULL,
  evidence_count INTEGER NOT NULL,
  source_diversity INTEGER NOT NULL,
  first_seen_at TEXT,
  last_seen_at TEXT,
  sample_evidence_json TEXT NOT NULL,
  public_state TEXT NOT NULL,
  PRIMARY KEY(src_ceid, dst_ceid, rel_type)
);

entity_event_rollup(
  ceid TEXT NOT NULL,
  event_id TEXT NOT NULL,
  relation_role TEXT NOT NULL,
  starts_at TEXT,
  venue_ceid TEXT,
  venue_name TEXT,
  city TEXT,
  is_future INTEGER NOT NULL DEFAULT 0,
  evidence_refs_json TEXT NOT NULL,
  PRIMARY KEY(ceid, event_id, relation_role)
);

entity_work_rollup(
  ceid TEXT NOT NULL,
  work_id TEXT NOT NULL,
  work_type TEXT NOT NULL,
  title TEXT NOT NULL,
  platform TEXT,
  public_url TEXT,
  published_at TEXT,
  evidence_refs_json TEXT NOT NULL,
  PRIMARY KEY(ceid, work_id)
);

graph_lens_cache(
  cache_key TEXT PRIMARY KEY,
  center_ceid TEXT NOT NULL,
  lens TEXT NOT NULL,
  nodes_json TEXT NOT NULL,
  edges_json TEXT NOT NULL,
  expires_at TEXT,
  built_at TEXT NOT NULL
);
```

索引：

```sql
CREATE INDEX idx_music_relation_src_type_weight ON music_relation_rollup(src_ceid, rel_type, weight DESC);
CREATE INDEX idx_music_relation_dst_type_weight ON music_relation_rollup(dst_ceid, rel_type, weight DESC);
CREATE INDEX idx_event_rollup_ceid_future_time ON entity_event_rollup(ceid, is_future, starts_at);
CREATE INDEX idx_work_rollup_ceid_type_time ON entity_work_rollup(ceid, work_type, published_at);
CREATE INDEX idx_graph_lens_center_lens ON graph_lens_cache(center_ceid, lens);
```

## 一框搜索逻辑

前台不展示实体类型选择器。类型判断在服务端完成。

流程：

1. 规范化 query：大小写、空格、全半角、标点、中文别名、平台 handle。
2. 精确候选：display name、alias、handle、source-scoped local id。
3. 前缀/容错候选：Meilisearch/SQLite FTS5，英文容错，中文不乱拆。
4. 语义候选：Qdrant hybrid 只补召回，不覆盖精确命中。
5. 图谱先验：PageRank、source_count、recent_activity、future_event_count。
6. 意图判断：根据 top candidate taxonomy 自动选 lens。

排名：

```text
score =
  exact_name * 1000
+ alias_or_handle * 700
+ prefix_match * 350
+ typo_match * 120
+ taxonomy_prior
+ pagerank * 20
+ log(source_count + 1) * 15
+ future_event_count * 8
+ relation_density * 5
- noise_penalty
- ambiguity_penalty
```

无论搜什么，结果卡片都用中文：

- `人物 / DJ`
- `空间 / 场地`
- `团体 / 厂牌`
- `活动 / 演出`
- `作品 / Mixtape`
- `来源 / 文章`

## 图谱窗口算法

### 场地窗口

默认节点预算 `300`：

- 中心场地：`1`
- 未来活动：最多 `16`
- 历史活动：最多 `40`
- 常见 DJ：最多 `60`
- 主办/厂牌：最多 `24`
- 城市/地址：最多 `6`
- 来源文章：最多 `30`
- 二跳 DJ->厂牌/合作对象：按权重补足剩余预算

### DJ 窗口

默认节点预算 `300`：

- 中心 DJ：`1`
- 未来演出：最多 `20`
- 历史演出：最多 `50`
- 常去场地：最多 `24`
- 常合作对象：最多 `36`
- 厂牌/团体：最多 `16`
- mixtape/作品：最多 `30`
- 公开主页：最多 `12`
- 来源文章：最多 `30`

### 厂牌窗口

- 关联艺人：最多 `60`
- 主办活动：最多 `50`
- 常合作场地：最多 `30`
- 作品系列：最多 `30`
- 公开主页/来源：最多 `30`

所有窗口都只返回精选 top-N，不能翻页枚举全库。

## 全中文界面

### 顶栏

- 品牌：`坏DJ Atlas`
- 副标题：`私有读模型 / 公开窗口`
- 搜索框 placeholder：`搜 DJ / 场地 / 厂牌 / 活动 / mixtape`
- 按钮：`搜索`、`漫游`、`适配`、`重置`、`导出 PNG`
- 深度：`1 跳`、`2 跳`、`3 跳`
- 布局：`径向`、`环形`、`分栏`

### 左侧栏

- `常用入口`
- `节点过滤`
- `关系过滤`
- `搜索结果`
- `探索记录`

### 图例

- 青色：`人物 / DJ`
- 金色：`俱乐部 / 场地`
- 绿色：`厂牌 / 组织`
- 橙色：`活动 / 演出`
- 灰色：`来源文章`
- 紫色：`作品 / Mixtape`
- 蓝色：`公开主页`

### 右侧详情

通用：

- `身份卡`
- `媒体`
- `来源证据`
- `字段`
- `外部链接`
- `候选主页`
- `本地链接`

DJ 专属：

- `未来演出`
- `历史演出`
- `常去场地`
- `常合作对象`
- `关联厂牌`
- `Mixtape / 作品`
- `公开主页`

场地专属：

- `未来活动`
- `历史活动`
- `常见 DJ`
- `合作厂牌 / 主办`
- `位置 / 城市`

厂牌专属：

- `关联艺人`
- `主办活动`
- `常合作场地`
- `作品系列`

## API 设计

```http
GET /api/v1/atlas/search?q=MaFoL&limit=12
GET /api/v1/atlas/graph/seed?q=MaFoL&lens=auto&limit=300
GET /api/v1/atlas/graph/lens?center=...&lens=dj-career&limit=300
GET /api/v1/atlas/entities/{ceid}/music-profile
GET /api/v1/atlas/entities/{ceid}/events?scope=future|history
GET /api/v1/atlas/entities/{ceid}/relations?type=regular_venue|collaborator|label|work|social
GET /api/v1/weekly/atlas-context?itemId=...
```

`lens=auto` 映射：

- `人物 / DJ` -> `dj-career`
- `空间 / 场地` -> `venue-ecosystem`
- `团体 / 厂牌` -> `label-network`
- `活动 / 演出` -> `event-lineup`
- `作品 / Mixtape` -> `work-context`

## 小程序 / 每日 LLM 联动

小程序每日活动生成时，只吃 materialized compact context：

```text
活动卡片
  -> 识别场地 / 阵容 / 主办
  -> Atlas 一框搜索候选
  -> 严格置信门禁
  -> weekly_atlas_context
  -> LLM 生成中文摘要、推荐理由、关联艺人/厂牌提示
```

小程序页面展示：

- 活动详情里显示 `Atlas 关联`
- DJ 名可打开 `艺人资料`
- 场地名可打开 `场地资料`
- 只显示 compact profile，不加载大图
- 需要深入探索时跳转 Web 图谱

## 反爬边界

- 搜索 top results 不超过 `20`。
- 图谱窗口必须签名并限量。
- `relations` 每类默认不超过 `12`，不会返回某 DJ/场地的全量历史。
- 不提供 `offset=全部`、`download=csv`、`export=json`。
- 前台 ID 不可顺序枚举。
- 文章正文、原始 SQLite、全量边表不出公网。
- 候选社交主页不等于 accepted 图谱关系。

## 验收用例

- 搜 `MaFoL`：第一结果必须是 MaFoL；默认打开 DJ 履历镜头；右侧出现历史演出、常去场地、候选/已接受主页分区。
- 搜 `DONG 洞`：默认打开场地生态镜头；显示历史活动、常见 DJ、关联主办/厂牌。
- 搜 `OIL` / `TAG`：不能被普通酒水、酒单、招聘、酒店推荐结果污染。
- 搜 `Do Hits`：默认打开厂牌网络镜头；显示关联艺人、活动和来源。
- 搜 `mixtape`：出现作品节点，但不能把普通推荐文章当成作品。
- 全中文界面：顶栏、左侧栏、图例、右侧 inspector、空状态、错误状态不得出现产品级英文。
