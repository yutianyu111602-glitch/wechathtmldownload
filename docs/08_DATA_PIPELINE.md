# 数据管道和每周活动增量文档 — 08_DATA_PIPELINE.md

项目: wechat-ingest + Stage7 weekly pipeline
更新: 2026-06-10

## 1. 管道总览

```
WeChat 公众号文章采集
  → HTML 归档 + 本地资产保留
  → MarkItDown HTML→Markdown 转换
  → LLM 结构化提取 (DeepSeek Flash/Pro)
  → Stage7 实体合并消歧 (event, DJ, venue, city, time_iso)
  → Source/Raw SQLite (3.8GB, 609K events)
  → Atlas Serving SQLite (1.6GB, 508K events)
  → 下游消费 (API / 微信小程序 / Web 图鉴)
```

## 2. 管道阶段详解

### L0: 源文章采集

- 入口: `npm run process-article -- <url>`
- 输出: HTML 文件 + 本地资产 (D:/rawwechat/)
- 模式: 单篇、批量、历史 URL 抓取

### L1: Markdown 转换

- 工具: MarkItDown (Python) + 本地 Tesseract OCR
- 命令: `npm run export:rawwechat-md`
- 输出: D:/rawwechat_md/

### L2: LLM 结构化提取

- 模型: DeepSeek Flash (批量), DeepSeek Pro (高质量)
- 命令: `npm run finalize-llm-pack`
- 输出: JSONL 结构化数据

### L3: Stage7 实体合并

- 脚本: `tools/stage7_rewrite/scripts/build_*.py`
- 流程: build → validate → gate → write
- 每次写入都需要 gate packet (dry-run → execute → verify)

### L4-L5: 数据库构建

- Source DB: 合并所有 Stage7 输出
- Serving DB: 从 source DB 构建优化后的只读副本
- 构建脚本: `build_atlas_serving_from_source.py`

## 3. 每周活动管道

每周活动推荐包的生成流程：

```
1. 采集本周 WeChat 文章 URL
2. 归档 HTML + 下载海报图片
3. OCR 海报提取文字 → 结构化活动信息
4. LLM DeepSeek Pro 补充描述/风格/阵容
5. 地理编码 (场地地址 → 经纬度)
6. 生成 API 数据包 (JSON)
7. CloudRun 部署 (替换 current_release)
8. 微信小程序重新生成离线快照
9. 上传微信审核
```

关键脚本：
- `tools/stage7_rewrite/scripts/weekly_activity_*.py`
- `tools/stage7_rewrite/weekly_activity_next_week_pipeline.ps1`
- `apps/weekly_activity_miniprogram/tests/smoke-test.cjs`

## 4. 数据库增量更新

### 增量来源

- 新的 WeChat 文章 → 新活动
- LLM 增强信息 → 字段更新
- 地理编码 → 坐标补充
- 外部链接采集 → DJ 社交资料

### 去重与幂等

- 活动去重: 标题相似度 + 时间 + 场地
- DJ 去重: 名称标准化 + 别名映射
- 写入前检查: `validate_*.py` 脚本验证
- 支持回滚: gate packet 提供 rollback contract

## 5. 导入命令参考

```bash
# 源数据导入 (从 Stage7 JSONL)
python tools/stage7_rewrite/scripts/build_atlas_serving_from_source.py \
  --source-db /tmp/atlas_merged.sqlite \
  --output reports/atlas_serving_new/atlas_serving.sqlite

# 每周数据包本地验证
python tools/stage7_rewrite/scripts/validate_weekly_current_release_drift.py \
  --api-dir services/weekly_activity_cloudrun/data/current_release

# 地理编码批量处理
python tools/stage7_rewrite/scripts/geocode_weekly_activity_places.py \
  --input <venues.jsonl> --output <geocoded.jsonl>
```

## 6. 外部大文件清单

详见 `EXTERNAL_ARTIFACTS_MANIFEST.md`

| 文件 | 大小 | 存储 | 用途 |
|---|---|---|---|
| atlas_merged.sqlite | 3.8GB | WSL /tmp/ | 源数据 |
| atlas_serving.sqlite | 1.6GB | reports/*/ | 服务数据 |
| atlas_db2.sqlite | ~500MB | WSL /tmp/ | 外链数据 |
| D:/rawwechat/ | TB级 | D: 盘 | 原始 WeChat HTML |
| D:/DDownload/_archive_mptext/ | TB级 | D: 盘 | mptext 归档 |

## 7. 数据质量检查

| 检查项 | 脚本 | 期望 |
|---|---|---|
| 字段完整性 | `validate_weekly_schema_compat.py` | 0 drift |
| 发布就绪 | `validate_weekly_current_release_drift.py` | 0 阻断 |
| 外链完整性 | `audit_atlas_db_field_contract.py` | 通过 |
| 坐标质量 | `audit_weekly_coordinate_quality.py` | 通过 |
