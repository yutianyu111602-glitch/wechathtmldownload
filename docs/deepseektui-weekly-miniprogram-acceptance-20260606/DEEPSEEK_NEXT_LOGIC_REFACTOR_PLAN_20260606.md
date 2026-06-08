# DeepSeek Next Logic Refactor Plan - Weekly Mini-Program - 2026-06-06

## 目标

DeepSeekTUI 下一阶段不要直接追着单个 bug 改 UI，而是先把“首次加载、海报、日期、source 跳转、geo、资源包质量”这几条互相影响的逻辑重新梳理成可验证的合同，再做小步拆分。

当前判断：项目不是不能维护，但 `utils/api.js`、`utils/format.js`、`pages/index/index.js` 已经形成局部核心耦合。继续往这三个文件堆功能，会反复出现“修海报影响 source、修日期影响首屏、修 geo 影响地图、修加载影响缓存”的回归。

## DeepSeekTUI 工作边界

允许：

- 读代码、读本接手包、跑本地测试。
- 写文档、写测试、做小步前端/工具脚本重构。
- 修本地 current release 包的可验证数据问题。

禁止，除非用户当前回合明确授权：

- CloudRun deploy。
- CloudBase DB/Storage 写入或 `weeklyDataSync` 生产同步。
- 微信小程序上传、提审、发布。
- 读取 `.env.local`、私钥、cookie、浏览器凭据。
- 清理、reset、delete 当前脏工作树。

## 当前事实

- 当前接手包入口：`/home/pc/deepseektui-handoffs/weekly-miniprogram-20260606/README.md`
- 本地代码 repo：`/mnt/c/code/githubstar/wechathtmldownload`
- 当前最该先读：`CLI_FULL_COVERAGE_DEBUG_RUNBOOK.md`
- 当前逻辑热点：
  - `apps/weekly_activity_miniprogram/utils/api.js`：网络、CloudBase、CloudRun、缓存、离线快照、fallback、去重/日期路径混在一起。
  - `apps/weekly_activity_miniprogram/utils/format.js`：字段归一、海报、日期、标题、source、去重、地图字段混在一起。
  - `apps/weekly_activity_miniprogram/pages/index/index.js`：首屏加载、进度、筛选、缓存提示、重试、海报预热、source 入口都在页面里。

## 总原则

1. 先补测试，再移动代码。
2. 先定义数据合同，再改 UI。
3. 每次只拆一层，不同时改加载、日期、海报、source。
4. 所有重构都必须保持现有外部行为，除非有明确 bug 证据。
5. 每个阶段结束都要跑本地质量门、Node 测试和必要 DevTools 证明。
6. 不把“本地测试绿”说成“体验版已修复”；体验版还需要 CloudRun/CloudBase/上传状态分别证明。

## Phase 0: 接手复核和最后 blocker

### Task 0.1 复核当前包

命令：

```bash
cd /mnt/c/code/githubstar/wechathtmldownload
python tools/stage7_rewrite/scripts/validate_weekly_release_package_quality.py \
  --api-dir services/weekly_activity_cloudrun/data/current_release \
  --report tools/stage7_rewrite/reports/weekly_current_quality_deepseektui_next_plan_recheck_20260606.json \
  --require-internal-posters \
  --enforce-window-start
```

验收：

- `ok=true`
- `missing_internal_poster_count=0`
- `aggregate_child_source_enabled_count=0`
- `missing_geo_count` 只剩已知 TRUST 场地，或补完后为 `0`

### Task 0.2 补最后一个 TRUST 场地 geo

目标：

- `trust:5b3d09797685195f`
- `阿派朗创造力星球(朝阳公园店)`

验收：

- 使用 `apply_weekly_manual_place_overrides.py` 写入用户确认的腾讯地图坐标、地址、POI。
- 质量门 `missing_geo_count=0`。
- `detail-map-location.test.cjs` 通过。

## Phase 1: 先写回归测试，把显性 bug 固化成合同

### Task 1.1 Loopy / aggregate-child source 合同

要覆盖：

- aggregate child 不得点击跳到父级“本周活动一览”。
- aggregate child 可以禁用原文跳转，但必须保留自己的 CloudBase 活动海报。
- 真实 direct source row 才展示原文入口。

可能文件：

- `apps/weekly_activity_miniprogram/tests/page-source-routing.test.cjs`
- `apps/weekly_activity_miniprogram/tests/source-articles.test.cjs`
- `apps/weekly_activity_miniprogram/utils/sourceAction.js`
- `apps/weekly_activity_miniprogram/utils/sourceArticles.js`

验收：

```bash
cd /mnt/c/code/githubstar/wechathtmldownload/apps/weekly_activity_miniprogram
node --test tests/page-source-routing.test.cjs tests/source-articles.test.cjs
```

### Task 1.2 日期过滤合同

要覆盖：

- 已结束活动不能因为来源文章发布日期或巡演父文标题误入 6 月 6 日。
- “本周一览 / 本月一览”类型行只显示原推文标题，不强行显示 DJ、日期、场地。
- date filter 使用 event date，不使用 post date 当活动日期。

可能文件：

- `apps/weekly_activity_miniprogram/tests/date-preview.test.cjs`
- `apps/weekly_activity_miniprogram/tests/production-data-source.test.cjs`
- `apps/weekly_activity_miniprogram/utils/datePreview.js`
- `apps/weekly_activity_miniprogram/utils/format.js`

验收：

```bash
node --test tests/date-preview.test.cjs tests/production-data-source.test.cjs
```

### Task 1.3 海报合同

要覆盖：

- durable poster truth 只能是 `cloud://.../weekly-posters/...` fileId。
- temp URL 只能用于运行时显示，不能写回包。
- public qpic/mmbiz 不能作为小程序包内海报真相。
- 主海报不能拿父级周/月一览图冒充活动图。

可能文件：

- `apps/weekly_activity_miniprogram/tests/cloud-poster-url.test.cjs`
- `apps/weekly_activity_miniprogram/tests/poster-pool.test.cjs`
- `apps/weekly_activity_miniprogram/utils/cloudPosterUrls.js`
- `apps/weekly_activity_miniprogram/utils/posterPool.js`
- `tools/stage7_rewrite/tests/test_validate_weekly_release_package_quality.py`

验收：

```bash
node --test tests/cloud-poster-url.test.cjs tests/poster-pool.test.cjs
python -m unittest tools.stage7_rewrite.tests.test_validate_weekly_release_package_quality -v
```

## Phase 2: 画清楚数据合同，再拆文件

DeepSeek 先输出一份 `DATA_CONTRACT_MATRIX_20260606.md`，不要先改代码。

必须列出：

| 领域 | durable truth | runtime/display truth | 禁止写回 |
| --- | --- | --- | --- |
| poster | `posterFileId/cloud://` | temp URL / local temp file | qpic、temp URL、wxfile |
| source | direct source hash/action | source page fallback | aggregate parent overview hash |
| date | event date start/end/guesses | UI compact label/filter label | post date 当活动日期 |
| geo | venue lat/lng + locked fields | `wx.openLocation` payload | promoter 当 venue |
| current feed | current release package | page view model | stale bundled snapshot 覆盖 current |

验收：

- 文档能解释 Loopy、DJ Love、Love Bang/POOLS、TRUST 这四类问题为什么发生。
- 文档明确每一类问题应该在后端包、前端格式化、页面加载还是 DevTools 渲染层修。

## Phase 3: 拆 `utils/api.js`

不要一次拆完。先做“外壳不变、内部搬家”。

建议目标结构：

```text
utils/api.js                         # public facade, 保持 require 路径兼容
utils/api/client.js                  # request / callContainer / public API
utils/api/cache.js                   # wx storage cache, cache key, TTL
utils/api/offlineSnapshot.js         # bundled/offline snapshot
utils/api/staticFallback.js          # static package fallback
utils/api/cloudbaseHot.js            # CloudBase hot DB / function path
utils/api/weeklyTransforms.js        # normalize/filter page payload
```

执行顺序：

1. 只抽 `cache.js`，测试通过。
2. 只抽 `offlineSnapshot.js`，测试通过。
3. 只抽 `cloudbaseHot.js`，测试通过。
4. 最后让 `api.js` 只负责编排和导出。

验收：

```bash
cd /mnt/c/code/githubstar/wechathtmldownload/apps/weekly_activity_miniprogram
node --test tests/api-static-fallback.test.cjs tests/weekly-data-sync-loading.test.cjs tests/production-data-source.test.cjs
```

DevTools 验收：

```bash
powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "Set-Location 'C:\code\githubstar\wechathtmldownload'; python tools\stage7_rewrite\scripts\run_miniprogram_devtools_rendered_single_attempt.py --script devtools-loading-fallback.cjs --port 9442 --avoid-busy-port --allow-dirty-devtools-environment --execute --timeout-sec 240"
```

## Phase 4: 拆 `utils/format.js`

先测试覆盖再搬。

建议目标结构：

```text
utils/format.js                      # public facade, 保持旧导出兼容
utils/format/canonicalize.js         # 字段归一
utils/format/poster.js               # poster durable/display 字段
utils/format/date.js                 # event date/date range/date labels
utils/format/source.js               # source overview/direct source guard
utils/format/mapLocation.js          # venue/geo/openLocation payload
utils/format/display.js              # title/list card display
utils/format/dedupe.js               # 去重 key 与相似项
```

执行顺序：

1. 抽 `date.js`，先解决日期逻辑测试。
2. 抽 `poster.js`，确保 fileId/temp URL 合同不变。
3. 抽 `source.js`，锁住 aggregate-child 行为。
4. 抽 `mapLocation.js`，锁住 promoter/venue 分离。
5. 最后处理 `canonicalize/display/dedupe`。

验收：

```bash
node --test tests/format-quality.test.cjs tests/date-preview.test.cjs tests/cloud-poster-url.test.cjs tests/page-source-routing.test.cjs tests/detail-map-location.test.cjs
```

## Phase 5: 拆首页 `loadData`

目标：页面只管 UI 状态，不直接承载请求编排。

建议目标结构：

```text
pages/index/index.js                 # page lifecycle and setData only
services/homeDataLoader.js           # first-load, current feed, metadata, fallback orchestration
services/homeFilters.js              # city/date/preview filters
services/homePosterView.js           # poster pool + image state adapter
```

执行顺序：

1. 抽纯函数 `homeFilters.js`，不碰网络。
2. 抽 `homePosterView.js`，不碰网络。
3. 抽 `homeDataLoader.js`，把 first-load/fallback/metadata Promise 编排移出去。
4. 首页保留 `loadData()` 作为薄 wrapper。

验收：

```bash
node --test tests/date-preview.test.cjs tests/poster-pool.test.cjs tests/weekly-data-sync-loading.test.cjs tests/page-event-handler-coverage.test.cjs
```

DevTools 必跑：

```bash
powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "Set-Location 'C:\code\githubstar\wechathtmldownload'; python tools\stage7_rewrite\scripts\run_miniprogram_devtools_rendered_single_attempt.py --script devtools-current-package-rendered.cjs --port 9430 --avoid-busy-port --allow-dirty-devtools-environment --execute --timeout-sec 240"
powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "Set-Location 'C:\code\githubstar\wechathtmldownload'; python tools\stage7_rewrite\scripts\run_miniprogram_devtools_rendered_single_attempt.py --script devtools-loading-fallback.cjs --port 9442 --avoid-busy-port --allow-dirty-devtools-environment --execute --timeout-sec 240"
```

## Phase 6: 增加一键本地验收脚本

新增脚本建议：

```text
tools/stage7_rewrite/scripts/run_weekly_miniprogram_local_acceptance.py
```

它只做本地验收，不做 deploy/upload。

必须执行：

- package quality validator
- Python validator/repair/manual geo tests
- mini-program Node core tests
- 可选 DevTools current render
- 可选 DevTools loading fallback

输出：

```text
tools/stage7_rewrite/reports/weekly_miniprogram_local_acceptance_YYYYMMDD_HHMMSS/
```

验收报告必须包含：

- package counts
- Python pass/fail
- Node pass/fail
- DevTools report paths
- deploy/upload/write all false unless user授权

## Phase 7: 只有验收绿后，才进入上传链路

上传前必须分开证明：

1. local package green
2. CloudRun remote effective green
3. CloudBase hot DB sync/readback green
4. DevTools rendered green
5. development upload green
6. review/release remains false unless用户明确要求

不能把其中任何一个当成另一个。

## DeepSeek 的最小下一步

如果只能做一个小步：

1. 补 `阿派朗创造力星球(朝阳公园店)` geo。
2. 跑质量门，目标 `missing_geo_count=0`。
3. 新增 `DATA_CONTRACT_MATRIX_20260606.md`，把 poster/source/date/geo/current feed 合同写清楚。
4. 给 Loopy、DJ Love、Love Bang/POOLS、TRUST 各补一个回归测试或 fixture。
5. 不动大重构，先提交测试和合同。

## Copy-Paste Prompt For DeepSeekTUI

```text
你接手 HUAIDJ weekly mini-program 下一阶段优化。不要直接大重构。
先读 /home/pc/deepseektui-handoffs/weekly-miniprogram-20260606/DEEPSEEK_NEXT_LOGIC_REFACTOR_PLAN_20260606.md 和 CLI_FULL_COVERAGE_DEBUG_RUNBOOK.md。
目标是再次整理首次加载、海报、日期、source 跳转、geo、资源包质量的逻辑耦合。
第一步补最后一个 TRUST 场地 geo 并让 missing_geo_count=0。
第二步写 DATA_CONTRACT_MATRIX_20260606.md，明确 durable truth、runtime/display truth、禁止写回字段。
第三步给 Loopy、DJ Love、Love Bang/POOLS、TRUST 建回归测试。
之后才按 api.js -> format.js -> index loadData 的顺序小步拆分。
每一步必须跑对应测试；不要 deploy、CloudBase 写入、上传、提审、发布或读取 secrets，除非用户当前回合明确授权。
```
