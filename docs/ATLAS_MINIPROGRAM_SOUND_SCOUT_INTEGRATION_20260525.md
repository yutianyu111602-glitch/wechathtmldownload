# Atlas 接入小程序与 Sound Scout 方案

Status: `CURRENT_INPUT` / `PRODUCT_PROPOSAL`

Updated: 2026-05-25 14:28 CST

Scope: `C:\code\githubstar\wechathtmldownload`

这份文档整理 Atlas 当前进度，并判断它接入微信小程序的可行路径。它不是生产授权文件；任何 CloudRun deploy、小程序上传/提审、Atlas pointer、Neo4j/Qdrant/SQLite 写入仍要走独立 gate packet。

## 一句话

Atlas 可以接入这个小程序，但第一步不应该让用户提交内容直接写入 Atlas。更稳的做法是：小程序负责收集 Sound Scout 设备线索，后端写入独立审核队列，审核通过后再进入 Atlas sidecar；Atlas 主库仍只由项目 owner 维护，Sound Scout 不授予主库写入、维护或审核权限。

## Atlas 目前进度

### 已经比较扎实的部分

- `138,102` 全量 full-LLM Atlas 基底已经有本地生产 marker 证据。
- 本地 Neo4j marker `stage7_all_full_llm_138102_prod_q6_social_20260524` 已验证。
- 最新 T5 serving/search/graph health refresh 已完成 report-only 检查，selected candidate 是 `reports\atlas_serving_field_repair_fullcomplete_strict_20260523-1658\atlas_serving.sqlite`。
- 该 refresh 再次确认 performance events `508,021`、DJ profiles `53,459`、DJ-event edges `1,285,428`、directed relations `699,800`、search docs/FTS `590,803/590,803`、graph windows `53,459`。
- 小程序详情页已经会请求 `/api/v1/weekly/atlas-events/:id`，并展示 Atlas verified / hint 艺人信息。

### 还不能说公网生效的部分

- `https://atlas.huaidj.club` 仍不能说 public-effective。
- Atlas public serving / pointer 仍被 public Stage7 smoke、session/identity、readback/pointer 证据挡住。
- 当前小程序开发版已上传，但 Codex 没有提交微信审核；正式用户可见状态不能合并进“已上传”。

### 社交身份和产品真值的边界

- Gekko、FullHouse、4Tael：只有本地 Neo4j `Stage7Staging` review metadata 写入验证，不等于 identity proof、avatar、public serving field 或 production graph label。
- `YYYY`：已有本地 staging-only HAS_PROFILE canary，但 product-truth mutation 因 `atlas_dj_id_missing` blocked。
- `Cod.Act`：有公共 SoundCloud metadata 候选，但本地 Atlas serving SQLite 没有 exact source context/profile/subject 命中，仍 blocked。

### 周活小程序当前可依赖的部分

- 当前远端后端是 CloudRun `weekly-api-066`，post-write smoke 通过。
- 压力验证是 `2101` requests / `0` failures。
- 当前 manifest item count `196`，materialized enrichment count `196`，current feed total `39`。
- 小程序已有详情页、场地页、艺人页、来源页、收藏页、关于页。
- 详情页已有 source articles、地址、地图、音响系统标签、Atlas lineup snapshot 的展示基础。

## 接入判断

### 结论

可以做，而且方向对。这个小程序天然适合做 Atlas 的轻入口，因为用户已经在看活动、场地、阵容和来源文章。Sound Scout 的价值是把“现场声音设备线索”变成可审核的城市级资料，而不是让用户在一个重型 Atlas 图谱后台里操作。

### 不建议的做法

- 不建议小程序直接写 `atlas.sqlite`、Neo4j、Qdrant 或 public pointer。
- 不建议把用户提交立即显示成“Atlas 已验证”。
- 不建议把 SoundCloud / 社交身份线索和音响设备线索混成一条通道。
- 不建议首版开放照片墙或公开评论流；这会放大审核、隐私和微信审核风险。

### 建议的做法

把接入分成三层：

1. 只读 Atlas 层：继续在活动详情页展示 Atlas verified / hint，保持现在的安全边界。
2. Sound Scout 贡献层：让用户补充场地或活动的主扩、低频、DJ 台设备线索。
3. Atlas 审核 sidecar 层：审核通过后写入独立 sidecar，再由批处理或人工 gate 合并到 Atlas。

## Sound Scout 产品定位

Sound Scout 是“城市声音设备线索员”。它不是社交身份，不是售票，不是评论区，而是一个给 Atlas 补现场设备证据的轻量贡献入口。

### 用户要做什么

- 补充主扩系统线索，例如 Funktion-One、d&b、L-Acoustics、Martin Audio、Void 等。
- 补充低频线索，例如 sub 型号、数量、摆放或明显的低频系统信息。
- 补充 DJ 台线索，例如 CDJ、XDJ、Technics、Allen & Heath、Pioneer、Ecler、rotary mixer 等。
- 上传或填写来源：公开文章、场地方公告、现场可核实文本、设备铭牌、活动图文证据。

### 用户得到什么

- 城市贡献榜。
- 可信贡献者身份。
- 优先 Atlas 只读内测查看资格。

### Atlas 得到什么

- 以场地为中心的 sound system profile。
- 以活动为中心的 equipment observation。
- 城市维度的声音系统地图。
- 可回溯的设备证据，而不是“音响很好”这种泛评价。

## 推荐信息架构

### 小程序入口

- 关于页：常驻入口，“成为 Sound Scout”。
- 活动详情页：当活动没有明确 sound system 时显示“补充设备线索”。
- 场地页：放最强入口，因为设备更稳定地绑定场地而不是单场活动。
- 城市页或榜单页：后续放“城市贡献榜”。

### 后端接口

建议新增一个独立命名空间，不混入现有 weekly item schema：

```text
POST /api/v1/sound-scout/submissions
GET  /api/v1/sound-scout/leaderboard?city=...
GET  /api/v1/sound-scout/me
```

首版只需要 `POST /api/v1/sound-scout/submissions`。榜单和身份可以先由审核后的 sidecar 生成静态 JSON。

### 提交数据结构

```json
{
  "schemaVersion": "sound_scout_submission.v1",
  "eventId": "weekly item id, optional",
  "city": "上海",
  "venueName": "EXIT",
  "equipmentArea": "main_pa | subwoofer | dj_booth | monitor | mixer | player | other",
  "brand": "Funktion-One",
  "model": "optional",
  "evidenceText": "来源或现场可核实描述",
  "sourceUrl": "optional public source URL",
  "sourceHash": "optional existing source hash",
  "confidence": "user_observed | source_backed | uncertain",
  "contactOptIn": false,
  "createdAt": "ISO timestamp",
  "status": "pending_review"
}
```

### 审核状态

- `pending_review`：用户刚提交，只进队列。
- `needs_more_evidence`：线索有价值，但证据不够。
- `accepted_sidecar`：审核通过，进入 Atlas sidecar。
- `atlas_candidate`：进入 Atlas 候选图谱，但还不是产品真值。
- `atlas_promoted`：通过独立 gate 后才成为 Atlas 可展示字段。
- `rejected`：品牌/型号不可信、泛评价、广告、隐私风险或明显错误。

## Sound Scout 文案

### 主入口

标题：

> 成为 Sound Scout

副标题：

> 补充主扩、低频、DJ 台设备线索，一起把中国地下电子音乐现场的声音档案补完整。

按钮：

> 补充设备线索

回报：

> 贡献会进入城市贡献榜。高质量线索会解锁可信贡献者身份，并优先获得 Atlas 只读内测查看资格。

### 活动详情页短文案

> 这场活动的设备信息还不完整。知道主扩、低频或 DJ 台配置？补一条线索，帮更多人判断现场声音取向。

按钮：

> 我知道设备线索

### 场地页短文案

> 你熟悉这个场地的声音系统吗？补充主扩、低频、DJ 台或监听设备，让城市声音地图更准确。

按钮：

> 补充这个场地

### 表单说明

> 请尽量填写可核实的信息：设备品牌、型号、位置、来源文章、现场照片或公开公告。泛泛的“音响很好”“低频很猛”不会直接进入 Atlas。

### 审核提示

> 提交后会先进入人工审核。通过前不会公开展示，也不会写入 Atlas 产品数据。

### 贡献榜文案

> 城市贡献榜记录被采纳的高质量设备线索。我们只展示贡献数量和身份徽章，不公开个人联系方式。

### 可信贡献者文案

> 连续提交可核实线索的用户，会获得可信贡献者身份。可信贡献者的线索会被优先审核，并优先获得 Atlas 只读内测查看资格。

### 反滥用提示

> 请不要上传他人隐私、后台证件、聊天记录或无法公开核实的内容。我们只需要设备线索和公开来源。

## 最小可行版本

### P0：文案与入口，不收数据

- 在关于页增加 Sound Scout 说明。
- 在详情页或场地页出现“补充设备线索”入口，但先跳转到说明页。
- 不新增后端写入，不影响微信审核风险。

### P1：提交队列

- 增加小程序表单页 `pages/sound-scout/sound-scout`。
- 增加 CloudRun `POST /api/v1/sound-scout/submissions`。
- 写入独立 JSONL 或 SQLite sidecar，不写 Atlas 主库。
- 提交后只显示“已收到，待审核”。

### P2：审核和榜单

- 增加本地审核脚本或简易审核工作台。
- 审核通过后生成 `sound_scout_accepted_sidecar.jsonl`。
- 生成城市贡献榜静态 JSON。
- 小程序只展示 aggregate leaderboard 和用户自己的状态。

### P3：Atlas 合并

- 由独立 builder 把 accepted sidecar 转成 Atlas equipment candidate。
- 先做 report-only packet。
- 再做 staging write gate。
- 最后才考虑 public serving field；Atlas 主库的维护动作仍只由项目 owner 执行。

## 安全边界

- Sound Scout 不是 Atlas 主库写入、维护或审核权限。
- Atlas 主库只由项目 owner 维护；内测资格只是只读查看资格。
- 用户提交不是事实，只是候选线索。
- 公开展示必须晚于审核。
- 设备线索优先绑定场地和活动，不优先绑定个人身份。
- 照片首版可以不做，避免隐私、审核和存储风险。
- 城市贡献榜只展示贡献结果，不展示手机号、微信号、openid 或私密联系方式。

## 下一步建议

1. 先把 Sound Scout 作为小程序里的“说明页 + CTA”接入，不写后端。
2. 然后做 `sound_scout_submission.v1` 队列和最小审核脚本。
3. 审核通过后的线索只进 sidecar，不进 Atlas 主库；Atlas 主库仍只由项目 owner 维护。
4. 等 `atlas_promoted` gate 做完，再让 Atlas 页面展示“主扩 / 低频 / DJ 台”字段。

## 相关代码入口

- 小程序详情页：`apps\weekly_activity_miniprogram\pages\detail\detail.js`
- 小程序详情页结构：`apps\weekly_activity_miniprogram\pages\detail\detail.wxml`
- 小程序场地页：`apps\weekly_activity_miniprogram\pages\venue\venue.js`
- 小程序关于页：`apps\weekly_activity_miniprogram\pages\about\about.wxml`
- 小程序格式化与 sound system 标签：`apps\weekly_activity_miniprogram\utils\format.js`
- weekly Atlas event API：`services\weekly_activity_cloudrun\src\server.mjs`
- `getAtlasEvent`：`services\weekly_activity_cloudrun\src\dataStore.mjs`
- Atlas local/read-only store：`services\weekly_activity_cloudrun\src\stage7AtlasSqliteStore.mjs`
