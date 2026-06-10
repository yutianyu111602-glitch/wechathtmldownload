# AI 接手总入口 — 00_AI_README.md

> **先读这个文件。** 下一位 AI 打开仓库后第一个必读的文档。

项目: wechat-ingest (wechathtmldownload) — 中国地下电子音乐图鉴数据管道
更新: 2026-06-10

## 1. 项目一句话说明

从 WeChat 公众号文章采集、归档、OCR、LLM 提取结构化数据，构建中国地下电子音乐场景的知识图谱（609K 事件、53K DJ、1.5M 实体），通过微信小程序（v2.6.9）和 Web 图鉴前端对外展示。

## 2. 技术栈

| 层 | 技术 | 位置 |
|---|---|---|
| 核心管道 | Node.js 20+, TypeScript strict | src/ (23 子目录) |
| 数据提取 | Python 3.11+, DeepSeek API | tools/stage7_rewrite/ |
| 图数据库 | Neo4j (staging), SQLite (serving) | reports/ |
| 向量搜索 | Qdrant (1024-d) | 本地 Docker |
| 前端 | 微信小程序 | apps/weekly_activity_miniprogram/ |
| Web 前端 | Atlas Graph UI (React) | huaidj.club |
| 桌面端 | Electron PCUI | desktop/main.mjs |
| 后端服务 | CloudRun (Node.js) | services/weekly_activity_cloudrun/ |
| 外部链接 | DB2 SQLite (12K+ social profiles) | WSL /tmp/ |
| 部署 | CloudBase, CloudRun, VPS (Ubuntu) | - |

## 3. 先读哪些文档 (按顺序)

1. **本文件** (00_AI_README.md) — AI 入口
2. `README.md` — 人类入口和运行时流程
3. `AGENTS.md` — Agent 行为边界和模型事实
4. `LONGRUN_STATE.md` — 当前长跑状态和数据库指标
5. `docs/current-runtime.md` — 最新运行时状态 (12K+ 行，最新证据)
6. `docs/03_ARCHITECTURE.md` — 高层架构 (NEW)
7. `docs/06_API_CONTRACTS.md` — 小程序 API 契约 (NEW)
8. `docs/07_DATABASE_SCHEMA.md` — 数据库结构 (NEW)
9. `docs/09_LOCAL_DEV_SOP.md` — 本地启动 (NEW)
10. `docs/13_SECURITY_PRIVACY.md` — 安全清单 (NEW)

## 4. 本地启动最短路径

```powershell
# 前置: Node 20+, Python 3.11+, 微信开发者工具
cd C:\code\githubstar\wechathtmldownload

# 构建 TypeScript
npm install
npm run build

# 管道 CLI (干跑测试)
npm run process-article -- --dry-run

# 微信小程序测试
node apps/weekly_activity_miniprogram/tests/smoke-test.cjs

# Python Stage7 测试
python -m pytest tools/stage7_rewrite/tests/ -q --timeout=30

# 启动桌面端
npm run start:gui
```

## 5. 最核心业务流程

```
WeChat 公众号文章 → 归档采集 (mptext/Dajiala)
  → HTML→Markdown 转换 (MarkItDown)
  → LLM 结构化提取 (DeepSeek Flash/Pro)
  → Stage7 实体合并/消歧 (event, DJ, venue, city, time_iso)
  → Atlas Serving SQLite (609K events, 53K DJs)
  → 微信小程序 API (CloudRun weekly-api)
  → 用户浏览/搜索/收藏
```

## 6. 最关键 API (CloudRun weekly-api)

| 端点 | 功能 |
|---|---|
| GET /api/v1/activities | 活动列表 (支持 city/time 筛选) |
| GET /api/v1/activities/:id | 活动详情 + 演出 DJ |
| GET /api/v1/djs | DJ 列表/搜索 |
| GET /api/v1/djs/:id | DJ 详情 + 演出历史 |
| GET /api/v1/venues | 场地列表 |
| GET /api/v1/search | 全文搜索 |

## 7. 最关键数据表 (Atlas Serving SQLite)

| 表 | 行数(约) | 含义 |
|---|---|---|
| performance_event | 508K | 演出事件 |
| dj_profile | 53.5K | DJ/艺人档案 |
| venue | 15K+ | 场地 |
| dj_event | 1.29M | DJ-事件关联 |
| search_document | 591K | 全文搜索索引 |
| graph_window | 53.5K | 图谱窗口 |

## 8. 最危险的坑

1. **不要运行生产级长跑任务** — 如 `full93k`、`batch500`、数据库写入
2. **不要连接生产数据库** — CloudRun 上的 weekly-api 使用的是 selected serving DB
3. **D: 盘禁止递归扫描** — D:\DDownload、D:\aidata 是 TB 级数据仓库
4. **不要运行 OCR/LLM 批处理** — 会消耗大量 API 配额和时间
5. **不要修改 selected serving SQLite** — 所有变更必须通过 gate/packet 流程
6. **不要提交 .env、数据库文件、日志到 Git**
7. **不要自动推送 CloudRun 部署** — 需要明确的 preflight gate

## 9. 不允许碰的东西

- `.env` 和 `.env.*` — 含真实 API Key
- 生产数据库文件 — `/tmp/atlas_merged.sqlite` (3.8GB)
- serving SQLite — 只读打开，禁止写入
- D:\DDownload, D:\rawwechat — TB 级原始数据
- CloudRun 生产服务 — 部署需人工确认
- WeChat 小程序上传 — 需要审核流程

## 10. 当前 UNKNOWN 清单

| 项 | 说明 |
|---|---|
| CloudBase 部署凭据 | 不在仓库中 (正确) |
| 微信支付配置 | 未发现 (可能未集成) |
| 用户认证方式 | 小程序端使用微信登录 (wx.login)，后端 session 机制 |
| Stage8/Stage9 生产边界 | 当前 gated，仅允许显式 canary/smoke |
| 完整 weekly pipeline 触发 | 由 OpenClaw cron 或手动触发 |

## 11. 测试入口

```powershell
# 前端 (129 tests)
node apps/weekly_activity_miniprogram/tests/<test>.test.cjs

# 后端 Python
python -m pytest tools/stage7_rewrite/tests/ -q

# Smoke test (8 checks)
node apps/weekly_activity_miniprogram/tests/smoke-test.cjs

# TypeScript 编译检查
npm run build
```

## 12. 下一位 AI 建议工作顺序

1. 读 `docs/00_AI_README.md` (本文件)
2. 读 `README.md` + `AGENTS.md`
3. 读 `docs/current-runtime.md` 最新段
4. 读 `docs/03_ARCHITECTURE.md`
5. 读 `docs/06_API_CONTRACTS.md`
6. 读 `docs/07_DATABASE_SCHEMA.md`
7. 本地按 `docs/09_LOCAL_DEV_SOP.md` 跑起来
8. 运行 `npm run build` 确认编译通过
9. 运行 smoke test 确认环境正常
10. 修改代码前检查 `docs/13_SECURITY_PRIVACY.md`
