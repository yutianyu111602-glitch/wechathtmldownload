# 交付物：周活小程序代码与文档只读审计

Audited: 2026-05-19  
Scope: mini-program + weekly CloudRun API + weekly docs（不含图鉴实现）

## 1. 现场验证

| 项 | 结果 |
|----|------|
| release guardian @ 20260519 包 | ok=true |
| backendRawHits / visibleHits | 51 / 0 |
| 远端 current + enrichment | 103 / 103 |
| 小程序单测 | 24/24 pass |
| DevTools E2E | 本机 cliPath 失败（非阻塞） |

## 2. 代码地图（~4500 行应用代码）

| 文件 | 行数 | 结论 |
|------|------|------|
| utils/api.js | 453 | 四级 fallback，强 |
| utils/format.js | 542 | 展示契约，掩盖 51 URL |
| pages/index/index.js | 462 | 全量分页；onLoad 无 query |
| pages/venue/venue.js | 64 | limit=100，注释未实现分页 |
| utils/posterPool.js | 109 | 48/24 海报池，有测 |
| tests/*.cjs | ~1500 | 24 pass |

无自定义组件；8 页面。

## 3. CloudRun weekly API

- 只读文件 API；`dataStore.dedupeItems` 服务端去重
- 小程序用：current, items/:id, batch, source/:hash, poster/:id, cities, dates
- Stage7 路由同服但小程序未调用

## 4. 缺陷清单

| ID | 严重度 | 问题 |
|----|--------|------|
| MP-1 | P0 | 51 URL 在 description_original_lines |
| MP-2 | P1 | 63/103 missing_lineup |
| MP-3 | P1 | venue/artist 仅 100 条 |
| MP-4 | P2 | city→index 深链断裂 |
| MP-5 | P2 | 三处去重可能漂移 |
| MP-6 | P3 | miniprogram-ci 未入 package.json |
| MP-7 | P3 | DevTools E2E 环境未就绪 |

## 5. 文档审计

### 权威

- NEXT_AGENT_HANDOFF_20260519_OPENCLAW_DAILY_RELEASE.md
- OPENCLAW_WEEKLY_DAILY_UPDATE_RUNBOOK.md
- OPENCLAW_AUTOMATION.md（顶部口径）
- SSOT.md weekly 专节
- WEEKLY_ACTIVITY_PUBLISHED_SCHEMA_V1

### 漂移

| 文档 | 应为 |
|------|------|
| DOCUMENTATION_INDEX.md | api-033 / 103 |
| current-runtime.md weekly 段 | 同上 |
| weekly_miniprogram_final_project_summary | 103 非 107 |

## 6. 管线契约

| 门 | 构建 | 小程序 | 一致 |
|----|------|--------|------|
| 无 source URL | filter | READY only | ok |
| needs_ocr_review | filter | 不展示 | ok |
| URL in UI | 未清 build | format 滤 | **分裂** |
| dj_bio | 恒 [] | 不展示 | 设计 |

## 7. lineup 审计数据点

- repair 20260519：`lineup_cleared` 34
- audit materialized：`missing_lineup` 63
- biofix2 历史：100 条中 16 有 lineup，hard_fail 0

## 8. 建议下一动作（只读优先）

1. guardian + 远端 reconcile（每日）
2. 确认 cron 脚本与 wrapper 一致性
3. 用户批准后：P0 golden（计划一）+ URL 清洗（本交付物）
