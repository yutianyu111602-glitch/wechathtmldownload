# HUAIDJ 小程序活动可见性契约（2026-07-19）

## 状态与读者

- 状态：`CURRENT CONTRACT`，适用于 2026-07-19 可见性修复线及其后续版本。
- 读者：小程序、CloudRun、CloudBase、活动包生成器和发布值班人员。
- 目标：让活动列表、城市数字、日期数字和海报永远描述同一个可见集合，并把“候选已生成”与“线上已公开”严格分开。
- 代码事实优先级：当前不可变发布工作树和本文件高于旧截图、旧发布报告、缓存、静态包及历史聊天。任何部署前仍须用当前代码和线上读回重新验证。

## 1. 为什么会出现“城市数字很大、信息流很少”

这不是单点前端显示错误，而是多个集合被混用：

1. 城市索引来自含历史活动的完整活动包，列表却只显示当前/未来活动。
2. “本周末”曾被压成一个周五日期，而不是周五到周日的闭区间。
3. 页面曾在内部使用周末筛选，但日期栏仍显示“全部日期”。
4. 切换城市会重置日期状态，用户看到的筛选条件与请求条件不同。
5. 海报池会用全国活动补齐城市结果，导致海报、列表和城市数字不属于同一集合。
6. 只读取第一页或错误地把 `nextCursor` 写成 `null`，会在 100 条处静默截断。
7. CloudRun 和 CloudBase 可能由不同快照生成，使同一路由在不同读取路径上返回不同数字。
8. 旧客户端以超大 `lookbackDays` 读取历史，而后端又有独立上限，最终形成无法解释的第三种口径。

修复原则不是“调小数字”，而是先定义唯一投影，再让所有展示面消费该投影。

## 2. 数据范围：`current` 与 `package`

| 范围 | 含义 | 允许用途 | 禁止用途 |
| --- | --- | --- | --- |
| `scope=current` | 用户当前可浏览的活动投影。无显式日期时，`lookbackDays=0` 表示今天及未来；有 `date` 或日期区间时，返回该显式区间。 | 首页、城市筛选、日期筛选、地图、海报、线上默认 API。 | 不得用完整包历史计数替代它。 |
| `scope=package` | 当前发布包的完整窗口，可含已经结束但仍需留作追溯、增量合并或审计的活动。 | 包校验、历史追溯、差异审计、显式管理查询。 | 不得作为小程序首页默认数字或默认信息流。 |

生成包的清单必须声明：

```json
{
  "static_index_scope": "package",
  "default_api_scope": "current"
}
```

静态 `cities`/`dates` 索引即使合法，也只证明 `package` 范围；客户端只有在响应明确返回匹配的 `scope=current`、日期窗口和数据数量时才可直接采用其计数，否则必须从当前可见项重建。

## 3. 日期状态机

页面必须持有显式 `dateMode`，不得用一个可空字符串同时表达“全部”“某一天”和“周末”。

| `dateMode` | 请求字段 | 语义 |
| --- | --- | --- |
| `all_current` | `date=""`, `dateStart=""`, `dateEnd=""` | 当前范围内全部日期。默认值。 |
| `exact` | `date=YYYY-MM-DD` | 只看该自然日。 |
| `this_weekend` | `dateStart=Friday`, `dateEnd=Sunday` | 从最近到来的周五到周日，首尾都包含。 |
| `next_weekend` | `dateStart=next Friday`, `dateEnd=next Sunday` | 下一组周五到周日，首尾都包含。 |

约束：

- 周末始终是三天闭区间 `[Friday, Sunday]`，不得退化为周五单值。
- `dateStart` 与 `dateEnd` 颠倒时，公共规范化层必须排序后再比较。
- 跨日活动按日期区间相交判断，不只比较开始日。
- 日期标签必须由当前 `dateMode` 生成；内部筛选不得与界面文字分离。
- 切换城市只改变 `cityKey`，必须保留当前 `dateMode`、`dateStart`、`dateEnd` 或 `exactDate`。
- “全部日期”显式回到 `all_current`，并清空日期字段。
- 活动业务日使用 `YYYY-MM-DD` 自然日键；发布与服务端值班以 `Asia/Shanghai` 为准。客户端周末键由本地日历生成，因此真实设备验收必须覆盖时区与周/月边界。

实现入口：

- `apps/weekly_activity_miniprogram/services/homeFilters.js`
- `apps/weekly_activity_miniprogram/pages/index/index.js`
- `services/weekly_activity_cloudrun/src/dataStore.mjs`
- `apps/weekly_activity_miniprogram/cloudfunctions/weeklyDataSync/index.js`

## 4. 唯一可见投影

对一次页面状态，先得到唯一集合：

```text
visible = electronic_relevant(
  date_projection(
    current_scope(all_published_items),
    dateMode
  )
)

display = city_projection(visible, selectedCity)
```

所有展示面必须由它派生：

| 展示面 | 数据来源 | 必须满足的等式 |
| --- | --- | --- |
| 信息流 | `display` | `totalItems == display.length` |
| 城市数字 | 对 `visible` 按城市分组 | 某城市数字等于切到该城市后的 `display.length` |
| 日期数字/日期可选项 | 对当前城市集合按日期分组 | 只出现该城市当前范围内实际存在的日期 |
| 海报 | `display` | 海报对应活动必须属于同一城市、同一日期投影；禁止全国补位 |
| 地图 | 完整分页后的 `current` 投影 | 不得只显示第一页 100 条 |

电子音乐相关性过滤必须发生在列表、城市/日期分面和海报分池之前；否则分面数字仍会包含页面最终丢弃的活动。

后端 `/current`、`/cities`、`/dates` 必须共同调用同一个可见性投影函数，并共同接受：

- `scope`
- `cityKey`（适用时）
- `date`，或 `dateStart`/`dateEnd`
- 兼容别名 `dateFrom`/`dateTo`
- `lookbackDays`（仅无显式日期的 `current` 默认投影）

缓存键必须包含上述所有会改变投影的字段。

## 5. 分页契约

`/api/v1/weekly/current` 响应的 `page` 至少包含：

```json
{
  "limit": 100,
  "cursor": "0",
  "nextCursor": "100",
  "total": 161
}
```

客户端必须循环读取，直到 `nextCursor` 为 `null`、空值或无效的非递增游标。不得把“第一屏已成功”当作“全集已读取”。CloudBase 同步也必须读取全部页后再写热库；缓存命中不得把原本存在的后续游标覆盖为 `null`。

每次验收至少加入一个 `total > 100` 的数据集，证明首页、地图、城市数字和 CloudBase 写入都未截断。

## 6. 在线加载与静态资源角色

生产默认读取顺序与职责：

1. CloudRun `weekly-api` 是小程序当前配置的在线活动主源。
2. CloudBase `weeklyDataSync` 数据库是同一在线发布的热镜像/可切换读取面，必须由 CloudRun 同步并读回验证。
3. 最近一次成功在线响应可作为短期本机缓存，但必须标记 `__fromCache`，后台刷新不能把旧缓存宣称为新发布。
4. `offlineSnapshot.js` 是固定的首次安装/灾难恢复种子，只在在线路径和持久化 last-good 都不可用时兜底。

关键边界：

- 当前活动增量包不随每次小程序代码版本重新生成或内嵌发布；活动更新应通过在线数据管线生效。
- `offlineSnapshot.js` 可以随代码包原样存在，但发布脚本必须校验其哈希未被活动包生成过程改写。
- 生产配置不得让快速灾备种子与健康的在线 `/current` 竞速；`fastOfflineSnapshotFallback=false`，默认在线请求的快照竞速关闭。
- `staticBaseUrl` 或远程静态 JSON 只是恢复/兼容读取面，不得成为不带 `scope` 的隐式权威。
- 页面出现“离线数据”提示时，不得用该画面作为线上活动数量证明。

实现入口：

- `apps/weekly_activity_miniprogram/app.js`
- `apps/weekly_activity_miniprogram/utils/api.js`
- `apps/weekly_activity_miniprogram/scripts/upload_devtools_cli_windows.ps1`（正式发布默认，使用真实微信开发者工具 CLI）
- `apps/weekly_activity_miniprogram/scripts/upload_native_windows.ps1`（仅在固定版本 `miniprogram-ci` 依赖和私钥均已验证时备用）

## 7. CloudRun 与 CloudBase 的一致性

一次活动发布至少产生一个可追踪的 `generatedAt`/发布包身份；一次 CloudBase 热同步另产生 `syncId`。`weeklyDataSync` 必须：

1. 从 CloudRun 分页读取完整 `current` 数据。
2. 把同一批 items、manifest 身份及生成时间写入 CloudBase。
3. 从同一 items 按 `scope=current` 生成城市和日期分面。
4. 返回并持久化同一个 `syncId`。
5. 读回 `/current`、`/cities`、`/dates`，核对 `syncId`、`generatedAt`、总数和代表性城市/周末窗口。

只看到 `syncId` 不等于同步正确；只看到 CloudRun 部署成功也不等于 CloudBase 已同步。发布证据必须同时保存同步响应和热库读回。

运维入口：

- `apps/weekly_activity_miniprogram/scripts/sync_cloudbase_database.cjs`
- `apps/weekly_activity_miniprogram/scripts/run_cloudbase_hot_sync_admin.cjs`
- `apps/weekly_activity_miniprogram/cloudfunctions/weeklyDataSync/index.js`

## 8. 测试与真实微信开发者工具发布门

最低测试层级：

```powershell
npm run test:miniprogram
npm run test:cloudrun
```

随后必须用本机真实微信开发者工具 CLI/Automator，而不是仅用 Node fixture：

```powershell
$env:MINIPROGRAM_DEVTOOLS_CLI = 'F:\DevApps\WeChatDevTools\2.01.2510290\cli.bat'
$env:USERPROFILE = 'F:\DevData\WeChatDevTools\Profile'
$env:LOCALAPPDATA = 'F:\DevData\WeChatDevTools\Profile\AppData\Local'
$env:APPDATA = 'F:\DevData\WeChatDevTools\Profile\AppData\Roaming'

python tools\stage7_rewrite\scripts\run_miniprogram_devtools_rendered_single_attempt.py `
  --script devtools-current-package-rendered.cjs --avoid-busy-port `
  --allow-dirty-devtools-environment --execute --timeout-sec 240

python tools\stage7_rewrite\scripts\run_miniprogram_devtools_rendered_single_attempt.py `
  --script devtools-loading-fallback.cjs --avoid-busy-port `
  --allow-dirty-devtools-environment --execute --timeout-sec 240
```

真实渲染验收必须检查：

- 工具版本、基础库版本和项目 AppID 正确。
- 默认是 `all_current`，不是隐藏周末。
- “本周末”标签与 `Friday..Sunday` 请求、列表完全一致。
- 城市数字等于切换后的唯一活动数。
- 切换城市保留周末范围。
- 海报全属于筛选结果且图片加载错误为零。
- `total > 100` 时完整翻页。
- 控制台无运行时异常。
- 黑洞/超时用例明确显示缓存或离线提示，不污染正式渲染证据。

上传前还要执行干净 staging 和灾备种子哈希门；上传必须记录版本号、描述、CLI 退出码和 `upload-info.json`。

## 9. 发布状态边界

下列状态不可互相替代：

| 状态 | 最低证据 | 不能宣称 |
| --- | --- | --- |
| 本地候选 | 代码、包、测试报告 | 已部署、用户可见 |
| 后端已部署 | CloudRun revision + 公网 smoke | CloudBase 已同步、小程序已上传 |
| CloudBase 已同步 | `syncId` + 数据库读回 | 小程序代码已上传 |
| 开发版本已上传 | 微信 CLI upload 成功 + 版本元数据 | 已提审、已公开 |
| 已提审 | 微信后台审核单 | 已通过、已公开 |
| 已公开生产 | 微信后台发布记录 + 真机公网读回 | 无 |

每次交接必须逐项写明，而不能只写“已更新”。

## 10. 回归禁令

- 不得用 `package` 城市计数给 `current` 首页。
- 不得把周末缩成单个周五。
- 不得在切换城市时隐式清空日期状态。
- 不得让全国海报补齐城市海报。
- 不得只读第一页或伪造 `nextCursor=null`。
- 不得让 CloudRun 与 CloudBase 分别从不同活动快照建索引。
- 不得把活动增量写回小程序灾备种子来“修复”线上数据。
- 不得把开发版上传、审核或公开发布混为一谈。
