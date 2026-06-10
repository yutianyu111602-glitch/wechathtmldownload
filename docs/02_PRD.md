# 产品需求文档 — 02_PRD.md

项目: 中国地下电子音乐图鉴 (HUAIDJ Atlas)
基于代码反推, 更新: 2026-06-10
证据来源: README.md, AGENTS.md, app.json, LONGRUN_STATE.md

## 1. 产品一句话说明

从 WeChat 公众号公开文章自动提取中国地下电子音乐活动信息，构建可搜索、可浏览的知识图谱，通过微信小程序和 Web 前端服务用户。

## 2. 用户角色

| 角色 | 来源证据 | 说明 |
|---|---|---|
| 游客/浏览者 | app.json (无强制登录) | 浏览活动、搜索 DJ/场地 |
| 微信用户 | wx.login 调用 | 收藏活动、提交 DJ 访谈 |
| 管理员/运营 | CloudRun admin 端点 | 管理数据、审核内容 |

## 3. 核心业务对象

| 对象 | 证据 (DB 表/代码) | 数据量 |
|---|---|---|
| 演出事件 | performance_event | 508K |
| DJ/艺人 | dj_profile | 53.5K |
| 场地 | venue | 15K+ |
| 城市 | performance_event.city | 24+ 城市 |
| DJ-事件关联 | dj_event | 1.29M |
| 微信公众号文章 | articles | 139K |

## 4. 功能模块

### 4.1 活动浏览 (首页)
- **代码**: `pages/index/index.*`
- 展示本周/近期活动列表
- 按城市筛选 (24 个城市)
- 按日期筛选
- 活动卡片: 海报、标题、时间、场地、DJ 阵容

### 4.2 活动详情
- **代码**: `pages/detail/detail.*`
- 活动完整信息
- DJ 阵容 (可点击进入 DJ 详情)
- 场地信息 (可点击进入场地详情)
- 原文链接 (WeChat 公众号原文)
- 来源信息: `pages/source/source.*`

### 4.3 DJ/艺人
- **代码**: `pages/artist/artist.*`
- DJ 个人页面: 名称、风格、简介
- 演出历史 (时间倒序)
- 社交链接 (SoundCloud, Instagram)

### 4.4 场地
- **代码**: `pages/venue/venue.*`
- 场地详情: 名称、地址、地图
- 活动历史

### 4.5 城市浏览
- **代码**: `pages/city/city.*`
- 按城市浏览活动

### 4.6 地图
- **代码**: `pages/map/map.*`
- 场地地图展示
- 需要用户位置权限

### 4.7 搜索
- **代码**: API /api/v1/search
- 全文搜索 (活动/DJ/场地)
- SQLite FTS5 引擎

### 4.8 收藏/ATLAS 计划
- **代码**: `pages/saved/saved.*`
- 用户收藏活动
- 个人活动计划

### 4.9 专栏
- **代码**: `pages/column/column.*`
- 专栏内容 (Tab 2)

### 4.10 声音
- **代码**: `pages/sound/sound.*`
- 音乐试听 (SoundCloud 嵌入)

### 4.11 DJ 访谈
- **代码**: `pages/interview/interview.*`
- DJ 访谈表单提交
- 支持 mixtape/Instagram 链接

### 4.12 关于
- **代码**: `pages/about/about.*`
- 项目介绍 (Tab 4)

## 5. 用户故事

1. 作为用户，我希望浏览本周电子音乐活动，按城市筛选
2. 作为用户，我想查看活动详情 (时间、阵容、场地)
3. 作为用户，我想了解某个 DJ 的演出历史和风格
4. 作为用户，我想搜索特定 DJ、场地或活动
5. 作为用户，我想在地图上查看场地位置
6. 作为用户，我想收藏感兴趣的活动

## 6. 业务规则

| 规则 | 证据 |
|---|---|
| 活动数据来自 WeChat 公众号公开文章 | README.md 管道流程 |
| 数据每周更新 | weekly pipeline |
| 不存储用户敏感数据 (openid 仅用于登录) | 安全审计 |
| 外链仅展示，不下载/代理媒体文件 | AGENTS.md 边界 |
| 访谈提交需外链验证 | externalLinkAction.js |

## 7. UNKNOWN / 需确认

| 项 | 说明 |
|---|---|
| 评论/互动功能 | 代码中未发现 |
| 支付/购票 | 代码中未发现 |
| 通知推送 | 代码中未发现 |
| 用户系统深度 | 仅 wx.login，无注册流程 |
| 管理后台 | 可能存在但不在小程序中 |
