# HUAIDJ 周活小程序 — 接手文档包索引



Updated: 2026-05-28 00:36 CST

Scope: **仅周活小程序线**（不含电子音乐图鉴主线实现，但计划二描述图谱联动边界）

## 跨线程路由（先读）

跨小程序、Docker exporter、Atlas、DeepSeekTUI 或文档统一口径的任务，先读：

- `..\threads\THREADS_INDEX_20260522.md` — 七线程总路由。
- `..\threads\T2_weekly_backend_release_20260522.md` — 周活后端/CloudRun 资源包线程。
- `..\threads\T3_mini_program_frontend_20260522.md` — 小程序前端/上传/审核状态线程。
- `..\threads\T4_atlas_activity_candidate_20260522.md` — 周活数据进入 Atlas activity sidecar / candidate DB 的 Route B 线程。

本目录仍是周活小程序线的细节包；Atlas 主线、DeepSeekTUI sidecar 和 docs/SSOT 现在由 `docs\threads` 分线程管理。

## 当前覆盖口径（2026-05-28 00:36）

- CloudRun backend 当前远端生效版本是 `weekly-api-066`；最新后端 deploy 证据仍是 `reports\WEEKLY_Q3_CACHE_KEY_BACKEND_DEPLOY_20260525.md`。
- 最新 package-root gate 是 `reports\WEEKLY_T2_T3_CURRENT_RELEASE_DRIFT_GATE_20260526.md`。它发现 local default `services\weekly_activity_cloudrun\data\current_release` 是 manifest/current/by-id `47/47/47`、GCJ-02 `0`、`2026-05-26` API-current total `32`；deploy-context `services\weekly_activity_cloudrun\tmp\cloudrun_deploy_context\data\current_release` 是 `196/196/196`、GCJ-02 `194`、API-current total `38`。两边内部一致，但根不一致。
- 最新 release-readiness hook 是 `reports\WEEKLY_T2_T3_RELEASE_READINESS_DRIFT_HOOK_20260526.md`。它把 package-root drift 接入 `build_weekly_release_candidate_dry_run.py`，真实 dry-run `tools\stage7_rewrite\reports\weekly_release_candidate_dry_run_with_drift_gate_20260526\weekly_release_candidate_dry_run.json` 返回 `release_candidate_local_gates_blocked` / `ok=false`，失败项 `current_release_no_default_deploy_drift=false`。
- 该 gate/hook 是 T2 package authority / release readiness blocker；本轮没有覆盖包、CloudRun deploy、小程序提审、凭据读取、network call、memory、D: root scan、destructive Git 或 Atlas DB/vector/graph write。
- T3 状态已更新：最新开发版上传为 `2026.05.28.2`，desc `vpn-map-external-active-venue-coverage`；Codex 未提交微信审核，正式用户可见版本未改变。该上传只覆盖小程序前端 developer version，不改变 CloudRun/backend authority。



## ⭐ 统一主计划（唯一执行入口）



| 文件 | 用途 |

|------|------|

| **[PLAN_WEEKLY_MINIPROGRAM_UNIFIED.md](./PLAN_WEEKLY_MINIPROGRAM_UNIFIED.md)** | **全文合一**：Phase II Sprint、RA/Atlas/去重/IA/UI、管线 Task、门禁、DoD |
| **[HANDOFF_CHECKPOINT_20260519.md](./HANDOFF_CHECKPOINT_20260519.md)** | **当前事实快照**：数字、已完成 Sprint、下一步 |
| **[DOC_CODE_PLAN_SYNC_AUDIT_20260521.md](./DOC_CODE_PLAN_SYNC_AUDIT_20260521.md)** | **文档生命周期/代码事实审计**：权威、历史、归档分层 |
| **[DEDUP_SOURCE_INTEGRATION_LOGIC_20260521.md](./DEDUP_SOURCE_INTEGRATION_LOGIC_20260521.md)** | **去重算法与推文来源整合 SSOT**：不重复发卡、不丢来源 |
| **[PRICE_OCR_TICKETING_GUARD_20260521.md](./PRICE_OCR_TICKETING_GUARD_20260521.md)** | **票价/OCR 抽取防线**：`3am 后免费入场` 不得显示为 `3元/￥3` |
| **[WEEKLY_MINIPROGRAM_ATLAS_EVIDENCE_PROVENANCE_V2_PLAN_20260521.md](../WEEKLY_MINIPROGRAM_ATLAS_EVIDENCE_PROVENANCE_V2_PLAN_20260521.md)** | **字段级证据/溯源 V2 新方案**：合并原升级计划与 deep research critique，按当时 `weekly-api-045` 基线重排 EvidenceRef、OCRSpan、PROV-lite、置信度、冲突、Atlas 只读和发布门禁；当前线上事实看 `docs\current-runtime.md` |
| **[PINGCHANG_TWO_ROUTE_HANDOFF_20260521.md](./PINGCHANG_TWO_ROUTE_HANDOFF_20260521.md)** | **Ping常 双路线接手**：Docker 自动取最新 auth key、79 条历史 URL、老抽取→Atlas staging、新规则 2 条周活 staging |
| **[SPRINT3_CLUB_SOURCE_CLOSEOUT_20260521.md](./SPRINT3_CLUB_SOURCE_CLOSEOUT_20260521.md)** | **Sprint 3 本地闭环**：Club Profile、source articles、organizer_key、routing/pagination |
| `reports\WEEKLY_INFO_SQUEEZE_STRATEGY_EVAL_20260521.md` | **信息榨干 / DeepSeek 策略评测**：600 次本地 DeepSeek 矩阵、票务 10-case 交叉验证、`--source-queue` 只读补源恢复 EXIT 分层票价 |
| `reports\WEEKLY_OCR_LLM_ATLAS_STRATEGY_AUDIT_20260521.md` | **2026-05-21 21:40 策略审计**：OCR/本地 LLM/Atlas 只读桥是否真正用上、票价误判修复、资源包-only `weekly-api-044` 证据 |
| `reports\WEEKLY_DISPLAY_COMPAT_BACKEND_SYNC_20260522.md` | **2026-05-22 显示兼容 + 后端资源同步**：`weekly-api-051` current 176、最早可见日期 2026-05-22、Ping常 2、莫须有公社 4、materialized LLM 176/176、promoter/account 裸 key 修复、title_display 截断修复、未上传前端、未提交新的微信审核 |
| `reports\WEEKLY_GEOCODE_BACKEND_DEPLOY_20260522.md` | **2026-05-22 GCJ-02 坐标后端发布历史证据**：腾讯 LBS 一键分配后全量 geocode，首轮 strict accepted 32 个地点，慢速二轮 accepted 9 个地点组 / 23 条活动坐标，活跃场地慢速三轮 accepted 14 个地点组 / 22 条活动坐标，next slow accepted 5 个地点组 / 12 条活动坐标，人工高德截图 + 腾讯 LBS accepted 5 个地点组 / 16 条活动坐标，后端包 `142/176` GCJ-02 坐标，CloudRun `weekly-api-056` 远端生效；只发后端，不上传小程序、不提审；已被 `weekly-api-061` 覆盖 |
| `reports\WEEKLY_DOCKER_SOURCE_GEOCODE_BACKEND_SYNC_20260522.md` | **2026-05-22 16:28 Docker 源刷新 + geocode 兼容后端发布历史证据**：Docker exporter `123/123` 账号成功、`8910` 推文元数据、`2026-05` 推文 `1074` 条；全量 OCR/LLM 后 API `196/196`，materialized LLM `196/196`，geocode 兼容恢复 `154/196` GCJ-02；CloudRun `weekly-api-058` 远端生效；只发后端，不上传小程序、不提审；已被 `weekly-api-061` 覆盖 |
| `reports\WEEKLY_MINIPROGRAM_VENUE_NIGHT_SOUND_FRONTEND_BACKEND_20260523.md` | **2026-05-23 16:48 场馆月排期 / 凌晨保留 / 音响系统 / 前端上传当前证据**：CloudRun `weekly-api-063` 远端生效；新增 additive `lookbackDays` 和 06:00 前上海 business-day cutoff；场馆页 `SOURCE ARTICLES` 走 `lookbackDays=31`；LLM/source-grounded 输出新增保守音响系统字段，后端-only 回填接受 `2/196` 条 source-backed `Funktion-One` 音响证据；小程序开发版仍为 `2026.05.23.1`，desc `venue-night-window-sound-system`；Release Guardian `ok=true`，pressure `6198/0`，DevTools haptics/extreme UI pass；Codex 未提交微信审核 |
| `reports\WEEKLY_MINIPROGRAM_8_PERCENT_LOAD_FRONTEND_FIX_20260524.md` | **2026-05-24 04:22 8% 加载卡顿前端修复**：后端 public API 现场探针健康，根因在客户端先等 `wx.cloud.callContainer` 后等 public fallback、重复点加载叠加多个 `loadData()` 请求组；本地前端改为 `publicFallbackDelayMs=1200` 后并发 public fallback，并给首页加载加 single-flight / queued retry / `loadSeq` guard；schema 兼容 `weekly-api-065`；mini tests `44/44`、public `/current` burst `20/20`、DevTools extreme UI `8/8`；本 slice 未上传小程序、未提审 |
| `reports\WEEKLY_MINIPROGRAM_FRONTEND_UPLOAD_20260527_1.md` | **2026-05-27 02:47 小程序前端开发版上传当前证据**：上传开发版 `2026.05.27.1`，desc `sound-atlas-fast-load`，zip buffer `185843`，upload exit `0`；包含关于页 Atlas 声场档案文案/未读红点、VPN/proxy 首开随包 snapshot 快路径、RA-style 俱乐部/DJ 入口、全局 i18n、详情地址 `wx.openLocation`、haptics 和 source article 显示；Node `54/54`、Release Guard mini-program tests `54/54`，DevTools loading/extreme/haptics 均 pass；Codex 未提交微信审核，正式用户可见版本未改变 |
| `reports\WEEKLY_MINIPROGRAM_FRONTEND_UPLOAD_20260528_2_ACTIVE_VENUE_MAP_COVERAGE.md` | **2026-05-28 00:36 小程序 active venue 地图覆盖开发版上传当前证据**：上传开发版 `2026.05.28.2`，desc `vpn-map-external-active-venue-coverage`，DevTools CLI upload zip buffer `215337` bytes，upload exit `0`；保留 VPN loading / 静默后台刷新 / 过期随包快照 fallback / 详情 `定位` / `huaidj.club` 复制链接 fallback；新增已接受 active venue registry 地图兜底覆盖 `62/62`；active venue map regression `62/62`、detail map `4` pass、API fallback `22` pass、纯 Node `58` pass / `0` fail、clean CI `ok=true`、DevTools loading/extreme/haptics 通过；Codex 未提交微信审核，正式用户可见版本未改变 |
| `reports\WEEKLY_MINIPROGRAM_FRONTEND_UPLOAD_20260528_1_VPN_MAP_EXTERNAL_FALLBACK.md` | **2026-05-28 00:10 小程序 VPN loading / 地图定位 / Atlas 外链 fallback 开发版上传上游证据**：上传开发版 `2026.05.28.1`，desc `vpn-map-external-fallback`，DevTools CLI upload zip buffer `214249` bytes，upload exit `0`；加载文案改为 `请关闭 VPN，后台刷新中`，cache/snapshot 首屏路径静默后台刷新，过期随包快照不会过滤成空首屏；详情地址改为 `定位` / `打开定位`，北京 `南营坊胡同日坛国际贸易中心` 坐标别名恢复 `wx.openLocation`；`huaidj.club` 改成受控复制链接 fallback，避免受限 web-view 错误页；已被 `2026.05.28.2` 取代为最新开发版 |
| `reports\WEEKLY_MINIPROGRAM_FRONTEND_UPLOAD_20260527_7_ATLAS_BETA_COPY.md` | **2026-05-27 20:56 小程序关于页 Atlas Beta 文案开发版上传上游证据**：上传开发版 `2026.05.27.7`，desc `atlas-beta-copy-full-access`，DevTools CLI upload zip buffer `210649` bytes，upload exit `0`；关于页更新为 `城市声音猎手 Atlas Beta` / `City Sound Hunter Atlas Beta`，直接通过现有 source/web-view 页打开 `https://huaidj.club/`，并限制直链 host 为 `huaidj.club` / `www.huaidj.club`；明确当前仍是 Beta，完整版将优先给提交高清设备/音响图片且通过人工确认和 LLM 一致性复核的俱乐部；about Atlas test `2` pass、about/haptics copy regression `4` pass、纯 Node `58` pass / `0` fail、clean CI quality `ok=true`、DevTools about copy/link probe `ok=true`；已被 `2026.05.28.2` 取代为最新开发版 |
| `reports\WEEKLY_MINIPROGRAM_FRONTEND_UPLOAD_20260527_6_ABOUT_ATLAS_LINK.md` | **2026-05-27 20:16 小程序关于页 Atlas 外链开发版上传上游证据**：上传开发版 `2026.05.27.6`，desc `about-atlas-beta-link`，DevTools CLI package `250006` bytes，upload exit `0`；关于页新增第一版 `城市声音猎手 Beta` / `City Sound Hunter Beta` Atlas 入口；已被 `2026.05.28.2` 取代为最新开发版 |
| `reports\WEEKLY_MINIPROGRAM_FRONTEND_UPLOAD_20260527_5_MAP_COORDINATE_COMPAT.md` | **2026-05-27 18:57 小程序地图坐标字段兼容开发版上传当前证据**：上传开发版 `2026.05.27.5`，desc `map-coordinate-compat`，DevTools CLI package `246024` bytes，upload exit `0`；修复前端地图坐标字段兼容，支持 Tencent/QQMap/Amap/GCJ aliases 和字符串/数组/嵌套 coordinate shapes，坏的旧字段不会挡住后面的确切坐标；补 `JAR这儿` / `JAR Club` 地址别名，离线快照地图覆盖 `8/8`；format/map regression pass、RA/map/source `10` pass、纯 Node `13/13` pass、clean CI quality `ok=true`；19:54 续跑 DevTools loading black-hole / extreme UI / haptics 均 pass；Codex 未提交微信审核，正式用户可见版本未改变 |
| `reports\WEEKLY_MINIPROGRAM_FRONTEND_UPLOAD_20260527_4_RA_MAP_ENTITY_UI_FIX.md` | **2026-05-27 18:33 小程序 RA/map/entity UI 修复开发版上传上游证据**：上传开发版 `2026.05.27.4`，desc `ra-map-entity-ui-fix`，DevTools CLI package `243712` bytes，upload exit `0`；修复详情页俱乐部/DJ 可点击实体入口、venue stale key fallback、artist 45-day lookback、详情地址 `wx.openLocation` 坐标兜底和 source hash 原文 URL 兜底；已被 `2026.05.28.2` 取代为最新开发版 |
| `reports\WEEKLY_MINIPROGRAM_FRONTEND_UPLOAD_20260527_3_CLEAN_CI_HARDENED.md` | **2026-05-27 14:39 小程序 clean-CI hardened 开发版上传当前证据**：上传开发版 `2026.05.27.3`，desc `clean-ci-validation-hardened`，zip buffer `185847`，upload exit `0`；`New-CleanCiStaging.ps1` / `Test-CleanCiQuality.ps1` 固化 repo-level clean staging，`upload_native_windows.ps1` 默认从 `artifacts\miniprogram-ci-staging\weekly_activity_miniprogram_upload` 上传；canonical quality `ok=true`、`__APP__=529652`，日志 `artifacts\miniprogram-ci-logs\check-code-quality-20260527-143146.log`；Codex 未提交微信审核，正式用户可见版本未改变 |
| `reports\WEEKLY_MINIPROGRAM_FRONTEND_UPLOAD_20260527_2_VALIDATION_FIX.md` | **2026-05-27 03:02 小程序验证修复开发版上传上游证据**：上传开发版 `2026.05.27.2`，desc `validation-clean-package`，zip buffer `185846`，upload exit `0`；根因是原项目根 quality validation 扫到 `test-artifacts`、历史 preview QR、上传日志和 package/test 文件，导致 `PACKAGE_SIZE_LIMIT=false` / `IMAGE_AND_AUDIO_LIMIT=false`；clean staging `artifacts\miniprogram-ci-staging-20260527` quality 全绿，package `__APP__=529652`；用户可见内容与 `2026.05.27.1` 一致；已被 `2026.05.27.3` 取代为最新开发版 |
| `reports\WEEKLY_REGISTRY129_GEOCODE194_BACKEND_DEPLOY_20260522.md` | **2026-05-22 20:40 registry129 geocode194 后端资源发布历史证据**：canonical registry `129` 源基线不变；SUBSTATION 经腾讯 LBS geocoder/reverse POI、公开页面和用户截图交叉验证后补入；CloudRun `weekly-api-061` 远端生效；manifest/package `196`，default current `195`，materialized LLM `196/196`，资源包 GCJ-02 `194/196`，default current GCJ-02 `193/195`，未补坐标仅 `TRUST 相信电音` 和 `Antigen.n` 两条电子音乐厂牌/主办方账号，不按场地补坐标；pressure `3392/0`，DevTools haptics/extreme pass；只发后端，不上传小程序、不提审；已被 `weekly-api-063` 覆盖 |
| `reports\WEEKLY_MINIPROGRAM_FRONTEND_UPLOAD_20260522_2.md` | **2026-05-22 22:39 小程序前端开发版上传历史证据**：上传开发版 `2026.05.22.2`，desc `title-cleanup poster-haptic-feed`，zip buffer `535033` bytes，code files `34`；保留 `wx.openLocation` 目的地地图，新增 `title_display` 污染清理，海报横滑震动改为和上下信息流同一套逻辑；上传前 mini-program tests `42/42` pass；Codex 未提交微信审核；已被 `2026.05.23.1` 覆盖 |
| `reports\WEEKLY_MINIPROGRAM_FRONTEND_UPLOAD_20260522_1.md` | **2026-05-22 22:10 小程序前端开发版上传历史证据**：上传开发版 `2026.05.22.1`，desc `weekly-api-061 map+haptic compat`，zip buffer `532013` bytes，code files `34`；包含 `wx.openLocation` 目的地地图和当时 restrained haptics；已被 `2026.05.23.1` 覆盖为旧开发版 |
| `reports\WEEKLY_REGISTRY129_BACKEND_DEPLOY_20260522.md` | **2026-05-22 19:08 129 公众号后端资源发布历史证据**：canonical registry `129`，Docker/exporter `125/125` 账号成功、`9013` 推文元数据、`2026-05` 推文 `1120` 条；候选包 `252 -> 199 -> 196`，materialized LLM `196/196`，GCJ-02 `175/196`，source hash/source-map missing `0/0`；CloudRun `weekly-api-060` 远端生效；只发后端，不上传小程序、不提审；已被 `weekly-api-061` 覆盖 |
| `tools\stage7_rewrite\reports\weekly_fullocr_old_pipeline_closeout_20260522.md` | **2026-05-22 13:59 老管线全量 OCR 本地收口**：确认先前 `PosterOcrLimit=80` 只是有限 OCR；用 `PosterOcrLimit=0` 补跑老管线后半，DeepSeek `1090/1090` failed `0`，本地 dated API `125/125`，materialized `125/125`，strict duplicate/conflict `0`，Atlas observations `125/125` source_url_hash，ingest dry-run pass；未覆盖当前 176 稳定包、未部署、未上传、未提审 |
| `reports\WEEKLY_MOXU_PING_BACKEND_SYNC_20260522.md` | **2026-05-22 03:51 后端资源同步历史证据**：`weekly-api-049` current 177、最早可见日期 2026-05-22、Ping常 2、莫须有公社 4、materialized LLM 177/177、票价/名字/NUTS 月排期日期修复；已被 `weekly-api-061` 覆盖 |
| `docs\current-runtime.md` | **2026-05-28 00:36 当前事实**：T3 小程序前端最新开发版为 `2026.05.28.2`，desc `vpn-map-external-active-venue-coverage`，upload exit `0`；已上传但未提审、正式用户不可见；本轮没有 CloudRun deploy、Atlas production 写入或新增定位权限。后端/资源包 authority 仍以 `docs\current-runtime.md` 和 T2 thread 当前条目为准。 |



以下 PLAN_* 已并入上文，**勿再当作执行入口**：`PLAN_MINIPROGRAM_NEXT_PHASE` · `PLAN_HV_ATLAS_RA_UI` · `PLAN_DEDUP_LOGIC_RA` · `PLAN_IA_SCHEDULE` · `PLAN_MASTER_INTEGRATED` · `PLAN_B_VECTOR_ATLAS_EXECUTION`



---



## 权威事实（当前）



| 项 | 值 |

|----|-----|

| CloudRun | `weekly-api-065`（以 `docs\current-runtime.md` 为准） |
| 发布条数 | manifest/package 196；2026-05-23 06:00 后默认 current 121；`lookbackDays=1` current 195 且包含 2026-05-22 活动 74 条；materialized LLM 覆盖发布包；source hash/source-map missing 0/0；可见占位账号/场馆名 0；year-like ticket 0 |
| 窗口 | `2026-05-22..2026-06-05` |
| 小程序开发版 | `2026.05.28.2` 是最新已上传开发版，desc `vpn-map-external-active-venue-coverage`；Codex 未提交微信审核，正式用户可见版本未改变 |
| API 包 | `D:\downstream_results\stage7_rewrite\longrun\WEEKLY_ACTIVITY_MINIPROGRAM_API_20260522_REGISTRY129_SYNC_1734` |
| OpenClaw 入口 | `tools\stage7_rewrite\run_openclaw_weekly_daily_publish.ps1` |
| 本次 guardian 复验 | 20:56 CST T3 关于页 Atlas Beta 文案复验：about Atlas test `2` pass，about/haptics copy regression `4` pass，纯 Node `58` pass / `0` fail，clean CI `ok=true`，DevTools about copy/link probe `ok=true` |
| 本次部署状态 | 本次最新只上传小程序开发版 `2026.05.28.2`；未部署 CloudRun、未提交微信审核，正式用户仍看不到该开发版 |
| 地图/标题/震动/场馆增强 | `2026.05.27.5` 实装地图坐标字段兼容：Tencent/QQMap/Amap/GCJ aliases、字符串/数组/嵌套坐标、`JAR这儿` 地址别名和离线快照 `8/8` 地图目标；继续保留 `2026.05.27.4` 的 RA-style 俱乐部/DJ 实体入口修复：俱乐部块更显眼并进入未来排期，DJ chip 进入历史演出记录，venue stale key fallback，artist 45-day lookback；详情页仍只用目的地 `wx.openLocation`，不 `wx.getLocation`，不 `navigateToMiniProgram`，不新增定位权限；保留标题清理、source article、海报横滑/上下信息流同逻辑震动、全局 i18n、关于页 Atlas 声场档案文案/未读红点；等待用户手动审核通过后才可能对正式用户可见 |
| 本次本地策略评测 | DeepSeek 矩阵 `600/600`；最优 `yellowpage_gate_v3 + flash no-thinking + temp 0.0/0.1`；票务 source regex `10/10`，当前包票务 exact `3/10`；本地 probe 包可从 source queue 恢复 EXIT 分层票价，未部署 |
| 日常更新策略 | 统一从 Docker exporter 当前账号/推文状态开始，先查是否有新关注公众号，再把同一批最新推文分两条路：A 路进小程序后端资源包，走 Docker exporter → 本地 OCR → LLM 物化 → 严格门禁 → CloudRun 后端/资源包部署；B 路进 Atlas 数据库，走 new-to-Atlas URL diff → HTML/OCR → source-preserving / activity-aware Atlas extraction → loss-chain audit → dated Atlas SQLite candidate → private source-url sidecar → public-safe serving read model。当前 activity-aware 桥接实现是 `tools\stage7_rewrite\scripts\build_atlas_activity_source_sidecar.py`，会先把 weekly/current rich fields、EvidenceRef v1.1 和 PROV-lite 写入本地 sidecar，再用 `merge_atlas_activity_sidecar_into_candidate_db.py` 合入派生 Atlas candidate DB。旧 generic Stage7 graph extractor 只能当二级图谱投影，不能宣称无损日更。默认不上传小程序前端、不提审；只有前端代码、权限、路由或不兼容 API schema 变化时才显式 `-UploadFrontend`。Atlas 原始库/Neo4j/Qdrant production 也不默认写入，需明确授权 |
| 服务器边界 | 新加坡服务器 / Singapore VPS 是炒股 beta 线，不属于周活小程序、Atlas 只读联动、Docker exporter、CloudRun weekly-api 或小程序上传链 |



| CloudRun / 上传证据 | latest backend deploy `tools\stage7_rewrite\reports\cloudrun_direct_deploy_sound_system_20260523_1630\cloudrun_direct_api_deploy_report.json`；latest smoke `tools\stage7_rewrite\reports\smoke_weekly_sound_system_20260523_1635\cloudrun_weekly_production_smoke.json`；latest pressure `tools\stage7_rewrite\reports\pressure_weekly_sound_system_20260523_1645\pressure_weekly_cloudrun_api.json`；latest report `reports\WEEKLY_MINIPROGRAM_VENUE_NIGHT_SOUND_FRONTEND_BACKEND_20260523.md`；latest API package `D:\downstream_results\stage7_rewrite\longrun\WEEKLY_ACTIVITY_MINIPROGRAM_API_20260522_REGISTRY129_SYNC_1734` |
| 本地全做收口 | `reports\ATLAS_WEEKLY_ALL_DO_CLOSEOUT_20260521.md`；含 Atlas 只读 detail 接口、本地 review/Golden/ingest/release dry-run 包 |

历史数量 `28/51/57/74/100/103/104/107/127/136/151/158/167/173/176/177` 以及 `weekly-api-058` / `weekly-api-060` 等 **不得** 当作当前线上事实。


---



## 文档清单



### 运维与状态（独立维护）



| 文件 | 用途 |

|------|------|

| [HANDOFF_CHECKPOINT_20260519.md](./HANDOFF_CHECKPOINT_20260519.md) | **检查点**（一页续跑，Sprint 末更新数字） |

| [DOC_CODE_PLAN_SYNC_AUDIT_20260521.md](./DOC_CODE_PLAN_SYNC_AUDIT_20260521.md) | **文档/代码/计划生命周期审计** |

| [DEDUP_SOURCE_INTEGRATION_LOGIC_20260521.md](./DEDUP_SOURCE_INTEGRATION_LOGIC_20260521.md) | **当前去重与推文来源整合逻辑** |

| [PRICE_OCR_TICKETING_GUARD_20260521.md](./PRICE_OCR_TICKETING_GUARD_20260521.md) | **票价/OCR 保护规则** |

| [PINGCHANG_TWO_ROUTE_HANDOFF_20260521.md](./PINGCHANG_TWO_ROUTE_HANDOFF_20260521.md) | **Ping常 双路线接手/自动 auth/历史下载/staging 证据** |

| [SPRINT3_CLUB_SOURCE_CLOSEOUT_20260521.md](./SPRINT3_CLUB_SOURCE_CLOSEOUT_20260521.md) | **Club/source local closeout** |

| [NEXT_AGENT_HANDOFF_WEEKLY_MINIPROGRAM_FULL.md](./NEXT_AGENT_HANDOFF_WEEKLY_MINIPROGRAM_FULL.md) | 2026-05-19 长版接手；**历史证据，当前数字看 CHECKPOINT** |

| [P0_EXECUTION_STATUS_20260519.md](./P0_EXECUTION_STATUS_20260519.md) | P0 执行状态 |

| [P0_BASELINE_REPORT_20260519.md](./P0_BASELINE_REPORT_20260519.md) | P0 baseline 报告 |

| [WeeklyAtlasEntityContract.md](./WeeklyAtlasEntityContract.md) | L0 契约全文（UNIFIED §8 为摘要） |



### 深度研究原文（归档，已摘要入 UNIFIED）



| 文件 | 用途 |

|------|------|

| [PLAN_A_DEEPRESEARCH_v2.md](./PLAN_A_DEEPRESEARCH_v2.md) | 计划一 LDR 强化稿 |

| [PLAN_B_DEEPRESEARCH_v2.md](./PLAN_B_DEEPRESEARCH_v2.md) | 计划二 LDR 强化稿 |

| [PLAN_A_WEEKLY_RECOGNITION_ACCURACY.md](./PLAN_A_WEEKLY_RECOGNITION_ACCURACY.md) | 计划一 v1 概要 |

| [PLAN_B_WEEKLY_ATLAS_ENTITY_LINKAGE.md](./PLAN_B_WEEKLY_ATLAS_ENTITY_LINKAGE.md) | 计划二 v1 概要 |

| [DEEPRESEARCH_RUN_20260519.md](./DEEPRESEARCH_RUN_20260519.md) | LDR 运行记录 |

| [archive/ARCHIVE_INDEX_20260519.md](./archive/ARCHIVE_INDEX_20260519.md) | 档案总索引 |



### 已合并计划（仅 diff/历史参考）



| 文件 | 并入 UNIFIED 章节 |

|------|------------------|

| [PLAN_MINIPROGRAM_NEXT_PHASE_20260521.md](./PLAN_MINIPROGRAM_NEXT_PHASE_20260521.md) | §9–11 |

| [PLAN_HV_ATLAS_RA_UI_INTEGRATED_20260520.md](./PLAN_HV_ATLAS_RA_UI_INTEGRATED_20260520.md) | §2–5、§8 |

| [PLAN_DEDUP_LOGIC_RA_20260520.md](./PLAN_DEDUP_LOGIC_RA_20260520.md) | §7 |

| [PLAN_IA_SCHEDULE_PLACEMENT_20260520.md](./PLAN_IA_SCHEDULE_PLACEMENT_20260520.md) | §6 |

| [PLAN_MASTER_INTEGRATED_20260520.md](./PLAN_MASTER_INTEGRATED_20260520.md) | §10 |

| [PLAN_B_VECTOR_ATLAS_EXECUTION_20260519.md](./PLAN_B_VECTOR_ATLAS_EXECUTION_20260519.md) | §8 |

| [PLAN_ROADMAP_20260519.md](./PLAN_ROADMAP_20260519.md) | §10.3 |



### 交付物与其它



| 文件 | 用途 |

|------|------|

| [DELIVERABLE_URL_TRACE_51.md](./DELIVERABLE_URL_TRACE_51.md) | 51 条 URL 溯源 |

| [DELIVERABLE_OPENCLAW_OBSERVATION_CHECKLIST.md](./DELIVERABLE_OPENCLAW_OBSERVATION_CHECKLIST.md) | OpenClaw 观测清单 |

| [DELIVERABLE_CODE_DOC_AUDIT.md](./DELIVERABLE_CODE_DOC_AUDIT.md) | 代码与文档审计 |

| [MEMORY_SYNC_20260519.md](./MEMORY_SYNC_20260519.md) | mem0 / agentmemory 同步 |

| [html/MASTER_DASHBOARD.html](./html/MASTER_DASHBOARD.html) | 可视化总览 |

| [html/](./html/) | Markdown HTML 伴生页 |

| `../../reports/ATLAS_WEEKLY_ALL_DO_CLOSEOUT_20260521.md` | **2026-05-21 全做收口**：本地 Atlas 只读联动、review 包、Golden 包、observations ingest dry-run、release dry-run 与门禁证据 |

| `../../reports/WEEKLY_EXPORTER_REFRESH_GATE_HARDENING_20260521.md` | **2026-05-21 续跑硬化**：Release Guardian 改为 exporter refresh effective 门禁；默认 release 模式因 `0/122` 成功账号、`ret=200003 invalid session` 而正确阻断；current-package 模式可验证既有 158 包 |


---



## 外部权威（仓库内）



- `NEXT_AGENT_HANDOFF_20260519_OPENCLAW_DAILY_RELEASE.md`

- `tools\stage7_rewrite\OPENCLAW_WEEKLY_DAILY_UPDATE_RUNBOOK.md`

- `apps\weekly_activity_miniprogram\OPENCLAW_AUTOMATION.md`

- `docs\WEEKLY_ACTIVITY_PUBLISHED_SCHEMA_V1_2026-05-08.md`

- `reports/ATLAS_WEEKLY_INTEGRATED_UNDERSTANDING_20260520.md`（Atlas 主线）



---



## 下一 agent 阅读顺序



1. 本 INDEX

2. `HANDOFF_CHECKPOINT_20260519.md`

3. **`PLAN_WEEKLY_MINIPROGRAM_UNIFIED.md`**

4. `DEDUP_SOURCE_INTEGRATION_LOGIC_20260521.md`

5. `SPRINT3_CLUB_SOURCE_CLOSEOUT_20260521.md`

6. `OPENCLAW_AUTOMATION.md` 顶部

7. 按需：`DELIVERABLE_*` · `PLAN_A/B_DEEPRESEARCH_v2` · `html/MASTER_DASHBOARD.html`



---



## HTML 生成



```powershell

$dir = "C:\code\githubstar\wechathtmldownload\docs\weekly-miniprogram-handoff-20260519"

$renderer = "C:\Users\pc\.codex\skills\html-handoff-summary\scripts\render_handoff_html.py"

python $renderer (Join-Path $dir "PLAN_WEEKLY_MINIPROGRAM_UNIFIED.md") -o (Join-Path $dir "html/PLAN_WEEKLY_MINIPROGRAM_UNIFIED.html") --kind handoff

Get-ChildItem $dir -Filter "*.md" | Where-Object { $_.Name -notin @("INDEX.md") } | ForEach-Object {

  python $renderer $_.FullName -o (Join-Path $dir "html" ($_.BaseName + ".html")) --kind handoff

}

```
