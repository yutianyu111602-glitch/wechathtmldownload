# Yuanbao CLI 接入方案

## 现状

Step 3.6 `expand_weekly_aggregate_articles.py` 用 DeepSeek Pro 从汇总文章提取子活动：
- 输入：文章 URL + body text
- 输出：子活动列表（标题/时间/场地/DJ）
- 问题：纯文本 LLM，无法识别图片中的活动海报归属

## 方案 A：替换 Step 3.6（推荐）

```
Step 3.6: Aggregate Article Expansion
  │  expand_weekly_aggregate_articles.py
  │  
  │  FOR each aggregate/overview article:
  │    ├── yuanbao ask "提取每个活动的标题/日期/DJ/海报图片URL" (via opencli)
  │    ├── 下载 yuanbao 识别的独立海报图片
  │    └── 写入 candidate pack
  │  
  │  Fallback: 如 yuanbao 不可用 → 回退到 DeepSeek Pro
```

**优势**：
- yuanbao 原生读 WeChat 文章 → 准确理解排期表
- 可直接识别每个子活动对应的海报图片（不需要 OCR）
- 一次调用替代 85 张图片的 MiMo 分类

**改动**：修改 `expand_weekly_aggregate_articles.py`，添加 `--use-yuanbao` 开关。

## 方案 B：接入 Recovery 管线

在 recovery pipeline 的 agg-child poster OCR 链路中：
```
aggregate_child_poster_ocr_recovery_tasks.json
  │  现有: 需要下载 HTML → 枚举图片 → MiMo OCR → 分类匹配
  │  新: yuanbao ask "读这篇一览文章，提取每天活动的海报图片URL" → 直接下载
```

## 方案 C：作为独立技能注册

新建 skill `openclaw-yuanbao-weekly`，触发词：`元宝解析本周活动`
```
skill 流程：
1. 读 current_release 找到所有 agg-children
2. 从 source_url_map 找到父文章 URL  
3. yuanbao 批量处理所有 URL
4. 下载海报 → CloudBase upload → patch package
```

## 建议

**先用方案 C 做独立技能验证效果**，确认 yuanbao 可以准确实别一览文章中的所有活动+海报。验证通过后，再合并到方案 A 的主管线 Step 3.6。

当前 11 个 agg-children 的父文章 URL 需要你提供——现有的 source_url_map 中的文章都是单日活动推文，不是"本周一览"类型。用 yuanbao 搜索这些公众号在 6月1-3日发布的"本周活动预告"文章即可获取正确 URL。
