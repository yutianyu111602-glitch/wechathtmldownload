# 小程序活动数据加载与离线灾备策略

状态：当前权威策略
核验日期：2026-07-18 CST
代码依据：`apps/weekly_activity_miniprogram/utils/api.js`、`services/weekly_activity_cloudrun/scripts/bake_and_deploy.py`

## 结论

活动数据不随小程序版本更新。常态更新只发布后端活动包；小程序在运行时读取线上 API，并持久化最近一次成功响应。场地页的俱乐部周/月/假期活动一览也属于后端活动包，通过 `/api/v1/weekly/club-overviews` 加载，不再由定时管线改写小程序源码。`utils/offlineSnapshot.js` 和 `data/club_overviews.js` 是首次安装且从未成功联网时的静态灾备种子，不是每周活动包、不是数据新鲜度来源，也不是普通发布门禁。

## 运行时顺序

1. 请求线上 weekly API。当前生产配置使用 CloudRun 公网入口；容器、公开路由和可选静态路由由 `api.js` 统一编排。
2. 每个成功的 `/api/v1/weekly/*` 响应写入微信本地存储。普通缓存窗口为 6 小时，用于网络较慢时快速恢复。
3. 所有线上路由失败后，读取同一请求键最近一次成功持久化的响应；此时忽略普通缓存时效，因为真实的历史响应仍优于首次安装种子。
4. 只有设备从未保存过对应成功响应时，才读取 `offlineSnapshot.js`。默认 current feed 仍过滤已经结束的活动，所以陈旧灾备种子允许返回空列表，不能冒充最新活动。

`club_overviews` 走同一套顺序：CloudRun 容器/公网（以及显式配置时的静态在线发布目录）→ 6 小时缓存 → 不限时最近成功响应 → 打包的 `data/club_overviews.js`。venue 页把它当作独立可选分支；该分支完全失败时只是不显示活动一览卡片，不得把场地活动、Atlas 历史或整个页面置为加载失败。

线上成功响应和静态灾备种子都必须经过当前活动过滤、去重和电子音乐相关性过滤。`__liveOnly=true` 同时绕过普通缓存、持久化镜像和静态灾备，用于新鲜度核验。

## 发布边界

- 后端活动更新：生成并校验活动增量包，更新 `current_release`，部署 CloudRun，远程读回。`club_overviews.json` 是活动包的可选线上文件，由 bake 复制到 `services/weekly_activity_cloudrun/data/current_release/club_overviews.json`；后端将它规范化后通过稳定路由发布。不得改写 `apps/weekly_activity_miniprogram/data/club_overviews.js`，不得上传小程序版本。
- 小程序代码更新：仅在前端代码、权限、交互、schema 兼容或灾备机制本身改变时单独上传开发版本。上传脚本会核对 staging 中 `offlineSnapshot.js` 与源码 SHA-256 完全一致。
- 灾备种子维护：只能单独运行 `tools/stage7_rewrite/scripts/generate_offline_snapshot.py`，并显式传入 `--confirm-disaster-seed-update`。修改后按前端代码变更执行完整测试和独立上传决策。
- 审核与公开发布：仍是开发者上传之后的独立状态，不由活动包更新自动触发。

普通 `bake_and_deploy.py` 不再提供任何刷新灾备种子的参数或代码路径。这样后端活动包、前端版本和微信审核不会再次被混为一个发布动作。

## 门禁

- 活动包和线上 API 的新鲜度门只检查后端 `manifest/current`、分页 ID、质量门和远程读回。
- 前端 fallback 测试必须把测试时钟固定到灾备种子的自身窗口；不得要求静态种子覆盖当前自然日。
- 灾备种子测试只验证格式、路由、过滤、source URL 映射和“无持久化结果时才使用”的优先级。
- `offlineSnapshot.js` 内容变化必须视作独立前端变更，不得由定时管线或 CloudRun bake 产生。
- `data/club_overviews.js` 同样只能作为独立前端灾备维护；定时任务只生成发布目录中的 JSON，普通 bake 不得调用导出器的 `--out-js` 路径。

## 最小验证

```powershell
node --test apps/weekly_activity_miniprogram/tests/api-static-fallback.test.cjs
node --test apps/weekly_activity_miniprogram/tests/ra-entity-navigation.test.cjs
node --test apps/weekly_activity_miniprogram/tests/production-data-source.test.cjs
python -m pytest tools/stage7_rewrite/tests/test_weekly_pipeline_repair_flags.py -q
python tools/stage7_rewrite/scripts/audit_weekly_miniprogram_all_pipelines.py --help
```

运行完整 release guardian 时，静态灾备种子的日期不应成为活动包发布失败原因。
