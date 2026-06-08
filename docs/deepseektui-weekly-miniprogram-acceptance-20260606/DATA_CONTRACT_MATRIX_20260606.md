# Data Contract Matrix — Weekly Mini-Program — 2026-06-06

> 本文档定义 poster、source、date、geo、current feed 五个领域的 durable truth、runtime/display truth 和禁止写回字段。
> 在改代码之前，先读懂这份合同。所有回归测试必须基于这份合同来写。

## 合同矩阵

| 领域 | Durable Truth (后端包 / CloudBase) | Runtime/Display Truth (前端运行时) | 禁止写回 |
|------|-------------------------------------|--------------------------------------|-----------|
| **Poster** | `posterFileId` = `cloud://.../weekly-posters/...` (CloudBase fileId)。后备链：`posterFileId` → `poster_file_id` → `coverFileId` → `cover_file_id` → `isCloudFileId(coverUrl)`。定义在 `cloudPosterUrls.js` `posterFileIdForItem()`。 | `posterTempUrl` = `wx.cloud.getTempFileURL()` 结果。仅用于 `<image>` 渲染，每次会话解析一次。`coverUrl` 可以是同一个 `cloud://` fileId，由前端替换为 temp URL。 | `posterTempUrl`、`posterDownloadFallbackTried`、`posterFileIdFallbackTried`、`posterLoadFailed`、`qpic`/`mmbiz.qpic.cn` URL、`http://`/`https://` URL、`wxfile://`。这些字段只存在于前端运行时，不得出现在 `weeklyDataSync` 写回的包中。 |
| **Source** | `sourceHash` = `source_action.url_hash \|\| source_article.url_hash`（源文章稳定标识）。`source_action.available` 控制是否显示原文入口。aggregate child (聚合子项) 的 `isAggregateChildItem()=true` 时，`sourceActionEnabled=false`，不展示原文跳转。 | 页面中 `openSourceByHash(hash)` 触发 `wx.navigateToMiniProgram` 或复制链接。aggregate child 保留自己的 CloudBase 海报但禁用原文入口。`isSourceOverviewItem()` 标记"本周一览/本月一览"行。 | aggregate parent overview hash 不得作为子项的 sourceHash；子项不得有 `source_action.available=true`（由 `aggregate_child_source_enabled_count` 验证）。 |
| **Date** | `event_date_start` / `event_date_end` (ISO 日期)。`event_date_iso_guesses` (数组，候选日期)。`window_start` / `window_end` 定义发布时间窗。这些是活动发生的真实日期。 | `dateLabel`、`dateRangeLabel`、`dateRangeCompact`、`weekdayLabel` — `format.js` `compactItem()` 产生的 UI 字符串。`isCalendarPreview` 标记"活动一览"行（不显示具体日期）。 | `post_date`（公众号发布日期）绝对不能当活动日期。已结束活动（`event_date_end < window_start`）不能被 `post_date` 带入当前窗口。`isSourceOverview` 行不显示 DJ、日期、场地。 |
| **Geo** | `venue` (数组)、`venue_name` (字符串)、`lat`/`lng` (腾讯地图坐标)、`address` (锁定地址)、`city_key`/`city` (城市)。坐标来自 `apply_weekly_manual_place_overrides.py` 写入的用户确认 POI。 | `wx.openLocation({ latitude, longitude, name, address })`。`listLocationLabel` / `cardLocationLabel` 为 UI 标签。`detail-map-location.test.cjs` 验证坐标传递。 | 厂牌 (label/promoter/系列名, 如 TRUST、Love Bang) 不得写入 `venue`/`lat`/`lng`。`promoter` 不得当 venue 用。`verifiedAddress()` 返回的值必须来自手动确认的 POI，不能自动生成。 |
| **Current Feed** | CloudRun API (`weekly-api-009`) 返回的 `manifest.json` 驱动的当前 release 包 (`services/weekly_activity_cloudrun/data/current_release/`)。`validate_weekly_release_package_quality.py` 定义质量门。 | 页面 `loadData()` → `requestApi()` → `compactItem()` → `dedupeItems()` → 产生页面 view model。通过 city/date 筛选器二次过滤。 | `OFFLINE_SNAPSHOT` (硬编码在 `api.js` 内的静态快照) 只能在网络完全不可用时作为最后 fallback，不得覆盖当前 release 包的数据。`manifest_provenance_stale` 触发 `ok=false`。 |

---

## 四类已知 Bug 的根因与修复层

### Bug 1: Loopy — aggregate child 跳到父级"本周活动一览"

- **现象**: 点击 Loopy 子项跳转到父级 overview 行，而非子项自己的页面。
- **根因**: aggregate child 的 `sourceHash` 被错误设置为父级 overview 的 hash。`isAggregateChildItem()` 检查通过，但 `source_action.url_hash` 指向了父级。
- **合同违规**: Source 合同的"禁止写回"列 — aggregate parent overview hash 不得作为子项 sourceHash。
- **应修层**: **后端包生成** — 确保 aggregate child item 在 `stage7_rewrite` 生成时，如果有自己的原文 hash，写入 `source_action.url_hash`；如果没有，`source_action.available` 设为 `false`。不要从父项继承 hash。
- **已验证**: 质量门报告 `aggregate_child_source_enabled_count=0`。

### Bug 2: DJ Love — 已结束活动误入当前窗口

- **现象**: DJ Love 活动实际日期已过，但因为 `post_date`（原文发布日期）落在窗口内，被展示为当前活动。
- **根因**: `format.js` 或 `api.js` 的 date filter 路径中，`post_date` 被当作活动日期使用。
- **合同违规**: Date 合同的"禁止写回"列 — `post_date` 绝对不能当活动日期。
- **应修层**: **前端 `format.js` 和 `api.js`** — 日期过滤必须使用 `event_date_start`/`event_date_end`，不能用 `post_date` 或 `sourcePublishedAt` 替代。如果 `event_date_start` 缺失，根据 `event_date_iso_guesses` 猜测，猜测不成功则标记为 `isCalendarPreview` 而非用 `post_date` 凑。
- **待验证**: 需要回归测试 fixture。

### Bug 3: Love Bang / POOLS — 海报用父级周/月一览图

- **现象**: Love Bang 和 POOLS 子项的主海报显示为父级"本周一览"的默认图，而非子项自己的活动图。
- **根因**: aggregate child item 的 `posterFileId` 或 `coverUrl` 未正确设置，fallback 到了父级 overview 的封面。
- **合同违规**: Poster 合同 — 主海报不能拿父级周/月一览图冒充活动图。
- **应修层**: **后端包生成 + 前端 `cloudPosterUrls.js`** — 确保每个 aggregate child 有自己的 `posterFileId`（即使用自己的 CloudBase 海报）。如果确实没有，`coverUrl` 应为空或使用占位，不从父项继承。
- **已验证**: 质量门报告 `missing_internal_poster_count=0`，但需要在渲染层验证海报来源。

### Bug 4: TRUST — 厂牌被误认为场地

- **现象**: TRUST 是厂牌（label），不是具体场地，但可能在数据中被当作 venue 处理。
- **根因**: 数据采集时未区分 label/promoter 和 venue。
- **合同违规**: Geo 合同的"禁止写回"列 — 厂牌不得写入 `venue`/`lat`/`lng`。
- **应修层**: **后端数据覆盖** (已处理) — 在 `apply_weekly_manual_place_overrides.py` 中不写入 TRUST。前端 `format.js` 中 `hasAddress` 字段对无场地项目应返回 `false`。
- **已验证**: 质量门报告 `missing_geo_count=0`。TRUST 作为厂牌不在缺失列表中。

---

## 修复层优先级

| 优先级 | 层 | 负责 | 说明 |
|--------|-----|------|------|
| 1 | 后端包 (`stage7_rewrite`) | 管线/脚本 | poster source date geo 的 durable truth 生成。最不容易引入前端回归。 |
| 2 | 前端格式化 (`format.js`) | 小程序 | `compactItem()` 中的 source/date/geo 归一。影响所有 UI 渲染。 |
| 3 | 前端加载 (`api.js`) | 小程序 | 网络/Cache/CloudBase/离线 snapshot 的编排。影响首屏和数据新鲜度。 |
| 4 | 页面渲染 (`index.js`) | 小程序 | 筛选、海报预热、source 跳转入口。依赖上述层产出。 |

---

## 验收标准

每层修复后必须通过：

1. **后端包**: `validate_weekly_release_package_quality.py` → `ok=true`, 全部 count = 0
2. **前端格式化**: `node --test tests/weekly-contract-regressions.test.cjs` → 全部 pass
3. **前端加载**: `node --test tests/weekly-data-sync-loading.test.cjs tests/api-static-fallback.test.cjs` → 全部 pass
4. **DevTools 渲染**: `run_miniprogram_devtools_rendered_single_attempt.py` → 首屏出现、无黑洞、海报可见

---

## 版本

- **创建**: 2026-06-06
- **基于**: `validate_weekly_release_package_quality.py` schema `weekly_release_package_quality.v1`
- **适用范围**: DeepSeekTUI / CodeWhale 接手周期。后端管线改动需要用户明确授权。
