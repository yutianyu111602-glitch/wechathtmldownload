# 前端微信小程序接手文档 — 04_FRONTEND_HANDOVER.md

项目: weekly-activity-miniprogram v2.6.9
WeChat AppID: wx0bc0a1d9d892af2d
更新: 2026-06-10

## 1. 入口文件

| 文件 | 作用 |
|---|---|
| `app.js` | 全局生命周期、globalData、离线快照配置 |
| `app.json` | 页面路由、TabBar、窗口配置、权限声明 |
| `app.wxss` | 全局样式（暗色主题 #000000 背景） |

关键配置 (`app.js`):
```js
offlineSnapshotFallback: true       // 必须为 true (曾导致黑屏)
fastOfflineSnapshotFallback: true
offlineSnapshotFallbackDelayMs: 2500
publicRequestTimeoutMs: 3000        // 曾为 1200，慢网络超时
```

## 2. 页面路由清单 (12页)

| 页面路径 | 标题 | 功能 | TabBar |
|---|---|---|---|
| pages/index/index | 活动列表 | 本周活动列表，城市/日期筛选 | Tab 1 |
| pages/detail/detail | 活动详情 | 演出详情、DJ阵容、场地信息 | - |
| pages/source/source | 素材来源 | 活动信息来源 | - |
| pages/artist/artist | DJ/艺人 | 艺人详情、演出历史 | - |
| pages/venue/venue | 场地 | 场地详情、活动历史 | - |
| pages/city/city | 城市 | 城市活动列表 | - |
| pages/saved/saved | ATLAS计划 | 收藏/计划 | Tab 3 |
| pages/about/about | 关于 | 关于页面 | Tab 4 |
| pages/column/column | 专栏 | 专栏内容 | Tab 2 |
| pages/map/map | 地图 | 地图展示场地位置 | - |
| pages/sound/sound | 声音 | 音乐/SoundCloud 试听 | - |
| pages/interview/interview | 访谈 | DJ 访谈表单提交 | - |

## 3. 前端服务层

| 模块 | 路径 | 职责 |
|---|---|---|
| API 封装 | `utils/api.js` | wx.request 封装，baseURL 配置 |
| 外部链接 | `utils/externalLinkAction.js` | 处理 mixtape/Instagram 外链 |
| 数据工具 | `utils/` 下其他文件 | 格式化、缓存、状态管理 |

**API baseURL**: 指向 CloudRun weekly-api (生产) 或本地 (开发)

## 4. 登录与鉴权

- 使用 `wx.login()` 获取 code
- Code 发送到后端换取 session
- Token 存储在本地 storage
- Token 失效时自动重新登录

## 5. 状态管理

- `app.globalData` — 全局共享数据
- 页面级 `data` — 页面状态
- Storage key 前缀: `weekly_`

## 6. UI 规范

| 属性 | 值 |
|---|---|
| 主题色 | #A7FF26 (荧光绿) |
| 背景色 | #050505 / #000000 |
| 文字色 | 白色 / #7E7E7E (次要) |
| 字体 | 系统默认 |
| 布局 | Flex 布局, rpx 单位 |

## 7. 测试 (129 tests)

测试目录: `tests/` (使用 `.test.cjs` 后缀, Node.js 环境运行)

| 测试类型 | 示例文件 |
|---|---|
| Smoke Test | `tests/smoke-test.cjs` (8 项检查) |
| API 完整性 | `tests/api-static-fallback.test.cjs` |
| 数据完整性 | `tests/extracted-data-integrity.test.cjs` |
| 格式化质量 | `tests/format-quality.test.cjs` |
| 事件处理覆盖 | `tests/page-event-handler-coverage.test.cjs` |
| 分享接线 | `tests/share-wiring.test.cjs` |
| 外部链接 | `tests/external-link-action.test.cjs` |

运行: `node apps/weekly_activity_miniprogram/tests/<name>.test.cjs`

## 8. 上传与发布

```powershell
# 通过微信开发者工具 CLI 上传
& "C:\Program Files (x86)\Tencent\微信web开发者工具\cli.bat" upload `
  --project "apps\weekly_activity_miniprogram" `
  --version X.Y.Z `
  --desc "description"
```

上传日志位于 `apps/weekly_activity_miniprogram/upload-*.log`

## 9. 已知问题

| 问题 | 状态 | 说明 |
|---|---|---|
| 15 张海报仍在 mmbiz CDN | 已知 | 需迁移到 CloudBase |
| `__subPageFrameEndTime__` 警告 | 已知 | 基础库 bug，不影响功能 |
| 离线快照回退 | 已修复 | `offlineSnapshotFallback: true` |
| 慢网络超时 | 已修复 | `publicRequestTimeoutMs: 3000` |

## 10. 调试方式

1. 微信开发者工具打开 `apps\weekly_activity_miniprogram`
2. 勾选"不校验合法域名"用于本地调试
3. 使用 miniprogram-automator 自动化测试:
```js
const automator = require('miniprogram-automator')
const miniProgram = await automator.connect({ wsEndpoint: 'ws://127.0.0.1:9421' })
const page = await miniProgram.currentPage()
console.log(await page.data())
```

## 11. 相关文档

- `apps/weekly_activity_miniprogram/ACCESS_GUIDE.md` — 访问指南
- `apps/weekly_activity_miniprogram/README.md` — 小程序 README
- `docs/FIELD_MAPPING_WEEKLY_MINIPROGRAM.md` — 字段映射
- `docs/WEEKLY_MINIPROGRAM_BLACKSCREEN_FIX_20260609.md` — 黑屏修复
