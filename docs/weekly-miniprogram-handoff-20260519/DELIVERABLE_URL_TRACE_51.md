# 交付物：后端 51 条 URL 溯源设计与实测

Updated: 2026-05-19  
Package: `D:\downstream_results\stage7_rewrite\longrun\WEEKLY_ACTIVITY_MINIPROGRAM_API_20260519`

## 1. 扫描方法

与 `huaidj-weekly-release-guardian\scripts\check_weekly_release_guard.ps1` 探针一致：

- 原始字段：`description_original_lines`, `dj_bio_lines`, `summary`, `description`
- 正则：`https?://`, `mmbiz.qpic`, `qpic.cn`, `wx_fmt=`, `from=appmsg`, `#imgIndex=`
- 可见层：`compactItem` 后 `descriptionLines` / `bioLines`

## 2. 实测结果

| 指标 | 值 |
|------|-----|
| 发布条数 | 103 |
| rawHits | **51** |
| visibleHits | **0** |
| 涉及字段 | **仅** `description_original_lines` |
| 涉及活动数 | **23** / 103 (22.3%) |
| URL 形态 | 全部为 `mmbiz.qpic.cn` 整行 CDN |

## 3. 高发活动（每 id 最多 3 行）

| event id | 行数 |
|----------|------|
| tangtangtang:5e86d5854dc6bcf9 | 3 |
| tomtwo:2142667973a0bac1 | 3 |
| dirty_house:ce92df09b77cbf74 | 3 |
| nu_lab:3f015c131135ead2 | 3 |
| dong:09c85265248aaa22 | 3 |
| potent:32fabb508702db79 | 3 |
| account_f07ee3e4a5:e9de7868aa948e97 | 3 |
| dirty_house:4adbc111e3a859ef | 3 |
| nuts:363cacac977044b8 | 3 |
| 另有 14 个 id 各 1–2 行 | |

完整行级列表：`C:\Users\pc\.cursor\projects\empty-window\url-hits-20260519.json`

## 4. 根因链

```
OCR/正文拆行 → DeepSeek pack → build API 写入 description_original_lines
  → 未剥离 URL → format.js 展示层过滤 → 用户不可见
```

- 非 source_map 问题（missing 0/0）
- 非前端漏过滤（单测通过）

## 5. 清洗设计（待实施）

| 决策 | 建议 |
|------|------|
| 位置 | `archive_old/build_weekly_activity_miniprogram_api.py` 写入前 |
| 规则 | 与 `format.js` DISPLAY_URL_RE 同构，删行 |
| 保留 | cover_image_url、poster API、source hash |
| 验收 | guardian `backendRawHits=0` 升为硬门 |

## 6. 复现命令

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File C:\Users\pc\.codex\skills\huaidj-weekly-release-guardian\scripts\check_weekly_release_guard.ps1 -CurrentReleaseDir D:\downstream_results\stage7_rewrite\longrun\WEEKLY_ACTIVITY_MINIPROGRAM_API_20260519
```
