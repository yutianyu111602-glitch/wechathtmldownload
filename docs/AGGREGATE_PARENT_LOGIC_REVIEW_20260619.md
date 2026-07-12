# 父聚合文章(本周/本月活动一览)逻辑审查 — 前后端合并视角

日期:2026-06-19
范围:只看"父聚合文章 → 子事件"这条链,前端(小程序)+ 后端(CloudRun serving)+ 构建端(stage7 Python)一起看。
结论一句话:**同一个"这是不是聚合"的概念,被三层、六处独立实现,字段集和大小写各不相同;后端 serving 层完全不参与,只在构建端(Python)和渲染端(前端 JS)各写了一遍,中间没有共享契约。这是"混乱"的根因,不是单点 bug。**

---

## 1. 数据模型:聚合是怎么产生的

一篇父文章(如「5月信号」「本周活动一览」「周末去处」)不是一个事件,而是一个排期合集。构建链的处理:

- `tools/stage7_rewrite/scripts/expand_weekly_aggregate_articles.py`(**1446 行**)负责:
  1. 用标题正则识别父文章(`AGGREGATE_TITLE_RE` / `AGGREGATE_MONTHLY_TITLE_RE` / `MONTH_TITLE_GENERAL_RE`,见 `tools/stage7_rewrite/scripts/expand_weekly_aggregate_articles.py:108`);
  2. 阻止父文章作为单个事件发布;
  3. 抽取二级文章链接,写 DeepSeek Pro / yuanbao 抽取缓存,拆成子事件。
- 拆出的子事件带 **三个并列信号**标记同一件事:
  - `id` 前缀 `agg-child-`
  - 字段 `aggregation_child: true`
  - `source_action.available = false` + `disabled_reason = "aggregate_child_parent_article"`(见驱动里的 source-URL 网关 `tools/stage7_rewrite/run_openclaw_weekly_daily_publish.ps1:272`)

子事件没有自己的原文(它们指向父文章),所以原文/海报都要回退到父文章——这是后面所有麻烦的来源。

---

## 2. 核心问题:同一概念,六处实现,各不相同

| # | 位置 | 判断的概念 | 实际检查的字段 | 问题 |
|---|------|-----------|---------------|------|
| A | `apps/weekly_activity_miniprogram/utils/format.js:322` `isAggregateChildItem` | 子事件 | `aggregation_child` + `aggregationChild` + id 前缀 | — |
| B | `apps/weekly_activity_miniprogram/utils/sourceArticles.js:13` `isAggregateLikeItem` | 子事件 | `aggregation_child` + `aggregationChild` + id 前缀 | 与 A 完全重复,两份代码 |
| C | `apps/weekly_activity_miniprogram/utils/sourceArticles.js:31` `isAggregateLikeRef` | 子事件(ref) | `aggregation_child` + (`event_id`/`id`/`source_event_id`)前缀 | **漏检 camelCase**;字段集与 A/B 不一致 |
| D | `apps/weekly_activity_miniprogram/utils/format.js:307` `isSourceOverviewTitle` | 父文章 | 标题正则(本周/本月/N月 + 一览/预告/…) | 前端**重新发明**了 Python 端的父文章检测 |
| E | `apps/weekly_activity_miniprogram/utils/format.js:1707` `isCalendarPreview` → "活动一览" 标签 | 父/预览 | 另一套判断 | 第三个相关但不同的概念 |
| F | `expand_weekly_aggregate_articles.py:108+` | 父文章 | 三个大正则 | 与 D 是同一分类的两套引擎,必然漂移 |

要点:
- **A 和 B 是逐字重复**的两份函数,分别 export,任何一个改了另一个不会跟。
- **C 漏了 `aggregationChild`(camelCase)**:同一个子事件,A/B 认得、C 认不得 → 列表里当聚合渲染、但在 source ref 链里当普通事件,原文卡片就会错乱。这正是用户感知到的"混乱"。
- **D/F 是父文章检测的两套正则引擎**(前端 JS 一套、Python 一套),判定边界不一样,且 Python 的 `MONTH_TOKEN_PATTERN` 还**硬编码成了"五月/may"**(`tools/stage7_rewrite/scripts/expand_weekly_aggregate_articles.py:61`)——是从某次 5 月跑批留下的,没参数化。
- **三个并列信号**(id 前缀 / `aggregation_child` / `disabled_reason`)标记同一件事:只要某条产出路径少写一个,六处消费方就会各自得出不同答案。

---

## 3. 后端 serving 层完全缺位

`services/weekly_activity_cloudrun/src/dataStore.mjs` 对 `agg-child` / `aggregation_child` **零感知**(grep 无命中)。子事件是构建端预先烤进包里、后端当普通 item 原样吐出。后果:

- "父文章绝不作为事件发布、子事件必须带父 provenance" 这条不变量,**没有任何 serving 层校验**;唯一的守门是 PowerShell 的 `Assert-PublishedItemsHaveSourceUrls`(对聚合子事件特判放行,`tools/stage7_rewrite/run_openclaw_weekly_daily_publish.ps1:272`)。
- 一旦 expand 步骤被跳过或某父文章漏检,父文章就会作为一个假事件直接发布,线上没人拦。
- 即"是否聚合"的真相在 **build(Python)** 和 **render(前端)** 各实现一遍,**serving(后端)** 不持有契约——这是割裂的结构性原因。

---

## 4. 衍生的子问题(都源自上面的割裂)

1. **原文链接易碎**:子事件 `source_action` 被禁用,`primarySourceRef` 对聚合返回 `null`、`sourceHashOf` 返回 `""`(`apps/weekly_activity_miniprogram/utils/sourceArticles.js:19/49`)。原文只能靠 `merge_provenance` 回退到父文章;provenance 一旦缺失/格式不对,子事件就**完全没有原文链接**。存在专门的修复脚本 `repair_weekly_aggregate_child_source_links.py` —— 它的存在本身就说明这条经常坏。
2. **海报恢复被做成了一整条子管线**:子事件常没有独立海报(父文章一张封面,子事件海报是正文内联图,要 OCR/视觉挑)。于是衍生出 **7 个脚本**:`build_weekly_aggregate_child_poster_ocr_{recovery_tasks,worker_contract,execution_preflight,controller_release_packet,runtime_release_preflight,source_material_preflight}` + `recover_agg_child_posters_mimo`。本质只是"为每个子事件挑对正文里那张海报",却堆了 6 层 preflight/packet/controller。这是过度工程。

---

## 5. 优化建议(按 ROI,先删后加)

**P0 — 统一"是否聚合"的判定(删重复,不加新东西)**
- 子事件用**单一信号**:保留 `aggregation_child: true` 作为权威字段,`agg-child-` id 前缀和 `disabled_reason` 降级为派生/校验用,不再让消费方各查各的。
- 前端把 A/B/C 合并成**一个** `isAggregateChild(itemOrRef)`,放在一处,统一检查 snake+camel+id 前缀;`sourceArticles.js` 和 `format.js` 都 import 它。直接修掉 C 漏检 camelCase 的 bug。
- 预计删掉 2 份重复函数 + 修 1 个真实渲染 bug,diff 很小。

**P1 — 父文章检测只留一处**
- 父文章分类是构建端职责。让 Python expand 在产出时把"父文章/预览"这个判定结果**写进字段**(如 `is_source_overview: true`),前端 D/E 直接读字段,删掉前端那套重复正则。一套正则引擎,消除漂移。
- 顺手把 `MONTH_TOKEN_PATTERN` 的硬编码"五月/may"参数化或改成通用月份匹配(`tools/stage7_rewrite/scripts/expand_weekly_aggregate_articles.py:61`)。

**P2 — 后端加一道契约校验(防父文章漏网)**
- 在 serving 加载包时校验不变量:`agg-child-` 前缀 ⇔ `aggregation_child===true` ⇔ `source_action.available===false`,三者必须一致;被判为父文章/overview 的 item 不得作为独立事件出现在 feed。不一致就拒载并报错,而不是依赖 PowerShell 网关。

**P3 — 海报子管线瘦身**
- 7 个 OCR packet/preflight 脚本合并成 1 个"为子事件选正文海报"的步骤(挑图 + 一次视觉确认),其余 controller/release/runtime preflight 层删掉。这是 ponytail 意义上的典型可删层。

---

## 附:一句话给到每一层
- **构建端(Python)**:你是唯一该做分类的人,请把结果写成字段,别让下游再猜。
- **后端(serving)**:你现在什么都不管,至少加一道"父文章不能当事件"的拒载校验。
- **前端(JS)**:你有四个重叠的判断,合成一个,顺手修掉 `isAggregateLikeRef` 漏检 camelCase 的 bug。
