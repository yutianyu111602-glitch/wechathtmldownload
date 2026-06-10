# EXTERNAL_ARTIFACTS_MANIFEST

项目: wechat-ingest (中国地下电子音乐图鉴数据管道)
生成日期: 2026-06-10

本清单记录所有不应上传 Git 的大型数据文件、数据库、原始增量包、媒体文件。这些文件体积过大（>50MB）或包含生产数据，不适合 Git 管理。

## 制品清单

| 制品 | 类型 | 位置 | 版本/日期 | 大小(约) | 是否脱敏 | 用途 | sha256 获取命令 |
|---|---|---|---|---|---|---|---|
| atlas_merged.sqlite | 源数据库 | /tmp/atlas_merged.sqlite (WSL) | 2026-06-01 | 3.8GB | 否 | 合并后的事件/实体源数据 | UNKNOWN_NEEDS_HUMAN |
| atlas_serving.sqlite (selected) | 服务数据库 | reports/atlas_serving_activity_current_time_dedupe_strict_20260525-1625/atlas_serving.sqlite | 2026-05-25 | 1.6GB | 否 | 当前 selected serving 数据库 | UNKNOWN_NEEDS_HUMAN |
| 报告 SQLite | 侧车数据库 | reports/atlas_*/*.sqlite | 多个日期 | 1-50MB | 部分 | 各类分析侧车数据库 | UNKNOWN_NEEDS_HUMAN |
| 每周活动增量包 (2026-06-10) | JSON | D:/downstream_results/stage7_rewrite/longrun/WEEKLY_ACTIVITY_MINIPROGRAM_API_20260610/ | 2026-06-10 | UNKNOWN_NEEDS_HUMAN | 否 | 最新 weekly 活动 API 输出 | UNKNOWN_NEEDS_HUMAN |
| 每周活动增量包 (merged) | JSON | D:/downstream_results/stage7_rewrite/longrun/WEEKLY_ACTIVITY_MINIPROGRAM_API_20260610_MERGED_CURRENT/ | 2026-06-10 | UNKNOWN_NEEDS_HUMAN | 否 | 合并后的 weekly API 包 | UNKNOWN_NEEDS_HUMAN |
| FullMap 数据 | JSON/JSONL | D:/downstream_results/stage7_rewrite/longrun/ | 每周 | GB级 | 否 | Stage7 完整 map 输出 | UNKNOWN_NEEDS_HUMAN |
| Dajiala 归档数据 | HTML/ZIP | D:/DDownload/_archive_mptext/ | 持续 | TB级 | 否 | WeChat 文章归档原始数据 | 不可扫描 |
| rawwechat 源数据 | HTML/资产 | D:/rawwechat/ | 持续 | TB级 | 否 | WeChat 文章原始 HTML 及资产 | 不可扫描 |
| 样例数据 (脱敏) | JSON/MD | services/weekly_activity_cloudrun/data/samples/ | 2026-06-10 | ~15KB | **是** | AI 接手用脱敏样例 | `git ls-tree HEAD services/weekly_activity_cloudrun/data/samples/` |

## 导入机制

各制品对应的导入/使用脚本：

| 制品 | 导入脚本 | 命令示例 |
|---|---|---|
| atlas_merged.sqlite | tools/stage7_rewrite/scripts/build_atlas_serving_*.py | `python build_atlas_serving_from_source.py --source-db <path>` |
| 每周增量包 | tools/stage7_rewrite/scripts/weekly_activity_*.py | `python import_weekly_increment.py --input <path>` |
| Dajiala 归档 | npm run dajiala-repair-archive-batch | 处理 Dajiala 重建后的 HTML |
| rawwechat 源数据 | npm run export:rawwechat-md | WeChat HTML -> Markdown 转换 |

## 存储建议

- 小型制品 (<1GB): 私有网盘或对象存储 (COS/OSS)
- 大型制品 (>1GB): 本地 NAS 或外部 HDD (D: 盘)
- 每周增量包: 对象存储，按周分目录
- 数据库备份: 私有网盘 + 本地副本

## 注意事项

1. 所有生产数据库包含真实用户数据（openid/unionid），不可分享
2. Dajiala 归档含 WeChat 平台版权内容，仅限个人研究使用
3. 本地开发使用脱敏样例数据，见 `services/weekly_activity_cloudrun/data/samples/`（仓库级入口：`data/samples/README.md`）
4. 外部制品路径中 `D:/` 指本地机械硬盘，非仓库内路径
