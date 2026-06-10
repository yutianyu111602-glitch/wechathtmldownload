# HUAIDJ Weekly Miniprogram — CHANGELOG

> 完整版本历史 | 始自 2026-05-09

---

## v0.4.0 (2026-05-12) — 设计规范合规 + 交互优化

### TabBar
- **新增**: 3 组 TabBar 图标 (本周/收藏/关于, 选中+未选中 6 PNG)
- **修改**: selectedColor `#7eb8da` → `#ffffff` (对比度合规)

### 交互优化
- **新增**: source 页返回按钮 (非 webview 模式)
- **新增**: detail 页 item 为空时空态 (`wx:elif="{{!item}}"`)
- **新增**: index 海报卡 `hover-class="poster-hover"` 点击反馈
- **新增**: index timeline 标题 `.linkable` 链接色+下划线
- **新增**: city 页 sub-nav 返回按钮 + `goBack()`
- **新增**: 全局 `.linkable` `.tap-hint` `.poster-hover` 样式

### 字体规范化 (25 处修复)
- **严重修复**: 13 处 20-21rpx → 24rpx (低于官方最小 12pt≈24rpx)
- **标准化**: 12 处 22rpx → 24rpx
- **统一层级**: 23rpx→24rpx, 25rpx→26rpx, 27rpx→28rpx, 29rpx→28rpx
- **最终层级**: 大标题 42-52 / 标题 32-34 / 正文 28-30 / 标签 24-26

### 性能
- **改进**: artist/venue 页 limit 50 → 100 (减少漏项概率)

### Bug 修复
- **Dockerfile**: crontab COPY 移除静默失败 `2>/dev/null || true`
- **Dockerfile**: 新增 `mkdir -p /app/logs` (cron 日志目录)
- **weekly_pipeline.sh**: 目录搜索 `WEEKLY_ACTIVITY_MINIPROGRAM_RELEASE_*` → `processed_*`

### CloudRun
- **重构**: `deepSeekClient.enrichEvent()` 改用 `llmEnrichment.mjs` 的丰富 prompt + 防幻觉规则
- **新增**: 4 个 LLM 路由测试用例 (enrich disabled/missing-id/404, weekly-summary disabled)
- **模块连接**: `llmEnrichment.mjs` 不再孤儿模块，通过 import 接入

### 文档
- **新增**: `DESIGN_AUDIT.md` (设计规范合规报告)
- **新增**: `AUDIT_v0.3.0.md` (全量代码审计报告)
- **新增**: `TECH_STACK.md` (技术架构)
- **新增**: `ACCESS_GUIDE.md` (接入指南)
- **新增**: `UNDERSTANDING.md` (项目理解)
- **新增**: `OPENCLAW_AUTOMATION.md` (自动化方案)
- **更新**: `HANDOFF_20260512.md` → v0.3.0 准确状态
- **新增**: 本文件 `CHANGELOG.md`

---

## v0.3.0 (2026-05-12) — LLM 集成 + 批量接口 + 页面完善

### 新功能
- **LLM 事件增强**: `deepSeekClient.enrichEvent()` — DeepSeek Flash 分析阵容/场地/风格
- **LLM 本周综述**: `deepSeekClient.generateWeeklySummary()` — 编辑推荐/趋势/城市分布
- **LLM API**: `/llm/enrich?id=` + `/llm/weekly-summary` (需 `DEEPSEEK_ENRICH_ENABLED=true`)
- **批量接口**: `/items/batch?ids=id1,id2,...` (逗号分隔, ≤100个)
- **Docker cron**: `weekly_pipeline.sh` + crontab 每周一自动管道
- **环境变量模板**: `.env.example`

### Bug 修复
- **saved 页**: limit=100 本地过滤漏项 → 改用 `/items/batch` 批量接口
- **about 页**: 空壳 `Page({})` → 版本号/CloudBase/版权
- **city 页**: 空壳 `Page({})` → 城市列表+跳转首页

### LLM 模块
- **新增**: `llmEnrichment.mjs` — 离线 LLM 标准化 schema (地址/票务/去重/审核标记)
- **新增**: `llmEnrichment.test.mjs` — 消息构建测试

---

## v0.2.3 (2026-05-12) — 交互修复

### Bug 修复
- 首屏海报卡点击 → 详情页
- 详情页海报区点击 → 源公众号文章
- 城市/日期弹窗内容可滚动 (`.logic-modal` 加 `overflow-y:auto`)

---

## v0.2.2 (2026-05-11) — 审核就绪

### Bug 修复
- 城市弹窗滚动修复
- 错误消息友好化 (不再暴露 errMsg)
- 新增 "重新加载" retry 按钮
- 城市/日期选项 `<button>` → `<view>` + `hover-class` (避免微信按钮默认行为)
- tap 即生效 (移除"确定"按钮中间步骤)
- modal-backdrop 点击关闭
- 海报卡 `openPosterSource` (hash优先→公众号→剪贴板兜底)

---

## v0.2.1 (2026-05-10) — 未上传

- 早期 tap-immediate 交互改动
- callContainer 链路调试

---

## v0.2.0 (2026-05-09) — 首次提交审核

### 初始实现
- 8 个页面骨架 (index/detail/source/artist/venue/saved/about/city)
- CloudRun 服务 `weekly-api` (Node 20 Alpine, HTTP 手动路由)
- 静态 JSON 数据层 (current.json / by-city / by-date / source_actions)
- `wx.cloud.callContainer` 通信链路
- `utils/api.js` + `utils/format.js` + `utils/sourceAction.js`
- `bake_and_deploy.py` 发布脚本
- WeUI 深色主题设计

### 已知问题
- 首次审核被拒 (-601034 errMsg 直接显示)

---

## 基础设施里程碑

| 日期 | 事件 |
|------|------|
| 2026-05-09 | CloudBase 个人版开通 (到期 2026-06-09) |
| 2026-05-09 | CloudRun weekly-api 首次部署 |
| 2026-05-09 | app.js + cloudbaserc.json envId 同步修复 (体验版→个人版) |
| 2026-05-09 | tcb CLI envId 补丁 (npm cache 重建后需重打) |
| 2026-05-12 | v0.3.0 全量审计 (47 源文件 + 6 文档 + 数据层) |
| 2026-05-12 | v0.4.0 设计规范合规审计 + 修复 |
