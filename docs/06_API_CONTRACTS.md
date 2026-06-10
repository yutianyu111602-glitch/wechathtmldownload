# API 契约文档 — 06_API_CONTRACTS.md

项目: weekly-activity-miniprogram ↔ CloudRun weekly-api
更新: 2026-06-10

## API 总表

| API ID | Method | Path | 功能 | 鉴权 |
|---|---|---|---|---|
| API-001 | GET | /api/v1/activities | 活动列表 | optional |
| API-002 | GET | /api/v1/activities/:id | 活动详情 | optional |
| API-003 | GET | /api/v1/djs | DJ 列表/搜索 | optional |
| API-004 | GET | /api/v1/djs/:id | DJ 详情 | optional |
| API-005 | GET | /api/v1/venues | 场地列表 | optional |
| API-006 | GET | /api/v1/venues/:id | 场地详情 | optional |
| API-007 | GET | /api/v1/search | 全文搜索 | optional |
| API-008 | GET | /api/v1/cities | 城市列表 | optional |
| API-009 | GET | /api/v1/cities/:id | 城市活动 | optional |
| API-010 | POST | /api/v1/interviews | 提交 DJ 访谈 | required |
| API-011 | GET | /api/v1/health | 健康检查 | none |

## API-001 活动列表

- **Method**: GET
- **Path**: `/api/v1/activities`
- **Auth**: optional (未登录也可浏览)
- **Query params**:

| 参数 | 类型 | 必填 | 说明 |
|---|---|---|---|
| city | string | 否 | 城市筛选 (如 "北京") |
| date | string | 否 | 日期筛选 |
| page | int | 否 | 页码 |
| limit | int | 否 | 每页条数 (默认 20) |

- **Response 200**:
```json
{
  "results": [
    {
      "id": "event_xxx",
      "title": "活动标题",
      "venue": { "id": "v_xxx", "name": "场地名", "city": "城市" },
      "starts_at": "2026-06-15T22:00:00+08:00",
      "djs": [{ "id": "dj_xxx", "name": "DJ名" }],
      "poster_url": "https://...",
      "source_url": "https://mp.weixin.qq.com/..."
    }
  ],
  "total": 508049,
  "page": 1,
  "limit": 20
}
```

- **Pagination**: 基于 page/limit 的偏移分页
- **Related DB**: `performance_event`, `venue`, `dj_profile`, `dj_event`

## API-002 活动详情

- **Method**: GET
- **Path**: `/api/v1/activities/:id`
- **Auth**: optional
- **Response 200**:
```json
{
  "id": "event_xxx",
  "title": "活动标题",
  "description": "活动描述 (LLM 提取)",
  "venue": { "id": "v_xxx", "name": "场地名", "city": "城市", "address": "地址" },
  "starts_at": "2026-06-15T22:00:00+08:00",
  "djs": [{ "id": "dj_xxx", "name": "DJ名", "bio": "简介" }],
  "poster_url": "https://...",
  "source_url": "https://mp.weixin.qq.com/...",
  "source_account": "公众号名称"
}
```
- **Related DB**: `performance_event`, `venue`, `dj_profile`, `dj_event`, `articles`

## API-003 DJ 列表

- **Method**: GET
- **Path**: `/api/v1/djs`
- **Auth**: optional
- **Query params**: `?q=搜索词&page=1&limit=20`
- **Response**: DJ 列表含名称、风格、演出次数
- **Related DB**: `dj_profile`

## API-004 DJ 详情

- **Method**: GET
- **Path**: `/api/v1/djs/:id`
- **Auth**: optional
- **Response**: DJ 完整信息 + 演出历史 (按时间倒序) + 社交链接
- **Related DB**: `dj_profile`, `dj_event`, `performance_event`

## API-007 全文搜索

- **Method**: GET
- **Path**: `/api/v1/search?q=搜索词&type=all|event|dj|venue`
- **Auth**: optional
- **Response**: 混合搜索结果 (活动/DJ/场地)
- **Related DB**: `search_document` (FTS5 全文索引)

## API-011 健康检查

- **Method**: GET
- **Path**: `/api/v1/health`
- **Auth**: none
- **Response**:
```json
{ "status": "ok", "db_size_mb": 1638, "event_count": 508049, "dj_count": 53555 }
```

## 错误响应格式

| 状态码 | 场景 |
|---|---|
| 400 | 参数错误 |
| 404 | 资源不存在 |
| 429 | 频率限制 |
| 500 | 服务器错误 (不返回详情) |

## 前端调用位置

前端调用位于 `apps/weekly_activity_miniprogram/utils/api.js`，各页面通过 `services/` 调用:
- `pages/index/index.js` → API-001
- `pages/detail/detail.js` → API-002
- `pages/artist/artist.js` → API-004
- `pages/venue/venue.js` → API-006
- `pages/city/city.js` → API-009

## 注意事项

1. 生产 API baseURL 指向 CloudRun (不在仓库中)
2. 本地调试时 API 指向 localhost:8787
3. API 从 serving SQLite 只读，不连接 source DB
4. FTS 全文搜索基于 SQLite FTS5
5. 小程序端使用 `publicRequestTimeoutMs: 3000`
