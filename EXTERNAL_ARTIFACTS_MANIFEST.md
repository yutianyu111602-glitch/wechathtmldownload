# EXTERNAL_ARTIFACTS_MANIFEST

项目: wechat-ingest (中国地下电子音乐图鉴数据管道)
生成日期: 2026-06-10

本清单记录所有不应上传 Git 的大型数据文件、数据库、原始增量包、媒体文件。这些文件体积过大（>50MB）或包含生产数据，不适合 Git 管理。

## 制品清单

| 制品 | 类型 | 位置 | 版本/日期 | 大小(约) | 是否脱敏 | 用途 | sha256 获取命令 |
|---|---|---|---|---|---|---|---|
| atlas_merged.sqlite | 源数据库 | /tmp/atlas_merged.sqlite (WSL) | 2026-06-01 | 3.8GB | 否 | 合并后的事件/实体源数据 | `sha256sum /tmp/atlas_merged.sqlite` |
| atlas_serving.sqlite (v4) | 服务数据库 | /tmp/atlas_serving_final_v4/atlas_serving.sqlite | 2026-06-01 | 1.6GB | 否 | 当前 selected serving 数据库 | `sha256sum <path>` |
| atlas_serving.sqlite (历史) | 服务数据库 | reports/atlas_serving_*/atlas_serving.sqlite | 多个版本 | 1.5-1.6GB | 否 | 历史版本服务数据库 | - |
| 报告 SQLite | 侧车数据库 | reports/atlas_*/*.sqlite | 多个日期 | 1-50MB | 部分 | 各类分析侧车数据库 | - |
| FullMap 数据 | JSON/JSONL | D:/downstream_results/stage7_rewrite/longrun/ | 每周 | GB级 | 否 | Stage7 完整 map 输出 | - |
| 每周活动增量包 | ZIP | D:/downstream_results/.../WEEKLY_ACTIVITY_*/ | 每周 | 450MB+ | 否 | 每周活动 OCR/提取结果 | - |
| Dajiala 归档数据 | HTML/ZIP | D:/DDownload/_archive_mptext/ | 持续 | TB级 | 否 | WeChat 文章归档原始数据 | - |
| rawwechat 源数据 | HTML/资产 | D:/rawwechat/ | 持续 | TB级 | 否 | WeChat 文章原始 HTML 及资产 | - |
| 产品 PDF | PDF | ProductIntroduction.pdf | - | - | 否 | 产品介绍 PDF | - |
| NIGHT_WATCHER 打包 | ZIP | NIGHT_WATCHER_COMPLETE_PACKAGE.zip | 2026-04-27 | - | 否 | Night Watcher 完整打包 | - |

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
3. 本地开发使用脱敏样例数据，见 data/samples/（待创建）
4. 外部制品路径中 `D:/` 指本地机械硬盘，非仓库内路径
