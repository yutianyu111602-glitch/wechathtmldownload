# Atlas 与微信小程序说人话版总结

Status: `CURRENT_AUTHORITY`

Updated: 2026-05-25 14:09 CST

Scope: `C:\code\githubstar\wechathtmldownload`

这份文档给人读，不替代技术核对报告。技术细节仍以 `ATLAS_MINIPROGRAM_CURRENT_PROGRESS_CODE_ARCHITECTURE_20260525.md`、`docs/current-runtime.md` 和 `docs/threads/THREADS_INDEX_20260522.md` 为准。

## 一句话

现在真正已经远端有效的是周活后端 `weekly-api-066`。微信小程序有开发版上传，但没有通过 Codex 提交微信审核；Atlas 本地证据和图谱推进了，但公网 Atlas 入口还没有正式生效。

## 当前状态

### 周活后端

这是当前最稳的一段。

- `weekly-api-066` 是远端有效状态。
- Q3 backend deploy 已完成，post-write smoke 通过。
- 远端压力探针是 `2101` 次请求、`0` 次失败。
- 当前 package manifest 是 `196`；2026-05-25 14:07 CST 的 current feed total 是 `39`。
- 这一轮只部署后端 cache-key 修复，没有切换 weekly resource package。

### 微信小程序

已经有开发版，但不能说正式用户已经可见。

- 小程序 appid 是 `wx0bc0a1d9d892af2d`。
- 当前名字是 `坏DJclub`。
- 页面包括本周、详情、来源、艺人、场地、城市、收藏、关于。
- 小程序通过 `wx.cloud.callContainer` 调 `weekly-api`，同时保留公网、静态、mock fallback。
- 开发版 `2026.05.23.1` 已上传，但 Codex 没有提交微信审核。

### Atlas

本地推进了，但还不能当作公网产品上线。

- 本地 Neo4j marker 已验证：`stage7_all_full_llm_138102_prod_q6_social_20260524`。
- Gekko、FullHouse、4Tael 的 product-truth review metadata 只写入了本地 staging 边。
- `YYYY` 有本地 staging-only canary，但 product-truth mutation 仍被 `atlas_dj_id_missing` 卡住。
- `Cod.Act` 仍 blocked：有公共 SoundCloud 元数据候选，但本地 Atlas serving SQLite 没有 exact source-context/profile/subject 命中。
- `https://atlas.huaidj.club` 仍不能说已经 public-effective。

## 不要混淆的状态

- 本地代码或本地数据库推进，不等于公网生效。
- weekly backend deploy 通过，不等于 Atlas 公网入口通过。
- 小程序开发版上传，不等于微信审核通过。
- 微信审核通过，也还要另证正式用户可见。
- T6/DeepSeekTUI/LDR sidecar 是研究证据，不是生产控制器。

## Understand-Anything 和 CodeGraph 怎么配

先用 Understand-Anything 画项目大图，再用 CodeGraph 查代码调用。

- Understand-Anything 负责回答：项目分几条线、当前事实入口在哪、哪些文档是 SSOT、哪些文件属于 Atlas/weekly/小程序。
- CodeGraph 负责回答：某个函数在哪里、谁调用它、它调用谁、改它会影响哪些 JS/Python 代码。
- 本仓库不默认全仓跑 CodeGraph，因为当前 untracked 文件是六位数。正确做法是先由 Understand-Anything 定出 Atlas + 小程序范围，再把 JS/Python 子集复制到 `.understand-anything/codegraph-atlas-miniapp-workspace` 里索引。

当前双图谱结果：

- Understand-Anything：`744` files，`5569` nodes，`4825` edges，校验通过。
- CodeGraph：`431` JS/Python files，`10465` nodes，`24031` edges，`node-sqlite` + `wal`，pending changes `0`。
- `getAtlasEvent` 在 `services/weekly_activity_cloudrun/src/dataStore.mjs:854`，直接 caller 是 `createServer`。
- `createServer` 在 `services/weekly_activity_cloudrun/src/server.mjs:448`，直接依赖 Stage7 store、Atlas security、DeepSeek client、weekly store 和页面渲染工具。

## 接下来最安全的事

1. `Cod.Act` 继续 blocked，直到有精确 Atlas source context 或 canonical id 证据。
2. `YYYY` product-truth mutation 继续 blocked，直到补齐 canonical target id。
3. 小程序继续把开发版、微信审核、正式用户可见三种状态分开记录。
4. Atlas public serving 只有在 public smoke、session/identity、pointer/readback 都清楚后再推进。
5. 任何 deploy、审核、生产写入前都先写 gate packet，并保留 rollback/readback 证据。

## 主要文件

- 技术核对报告：`docs/ATLAS_MINIPROGRAM_CURRENT_PROGRESS_CODE_ARCHITECTURE_20260525.md`
- 说人话 HTML：`docs/ATLAS_MINIPROGRAM_HUMAN_SUMMARY_20260525_STANDALONE.html`
- 当前运行状态：`docs/current-runtime.md`
- 七线程路由：`docs/threads/THREADS_INDEX_20260522.md`
- Understand-Anything 图谱：`.understand-anything/knowledge-graph.json`
- Understand-Anything 摘要：`.understand-anything/focused-atlas-miniapp-summary.json`
- CodeGraph 状态：`.understand-anything/codegraph-atlas-miniapp-status.json`
- CodeGraph 上下文：`.understand-anything/codegraph-atlas-miniapp-context.md`
