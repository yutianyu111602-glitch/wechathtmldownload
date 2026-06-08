# 接手检查点 — 2026-05-19（2026-05-22 05:02 显示兼容修复 + 后端资源同步）

> 精简续跑入口。执行计划见 **[PLAN_WEEKLY_MINIPROGRAM_UNIFIED.md](./PLAN_WEEKLY_MINIPROGRAM_UNIFIED.md)**；Sprint 1 closeout 见 [SPRINT1_GATE_CLOSEOUT_20260521.md](./SPRINT1_GATE_CLOSEOUT_20260521.md)；Sprint 2 parity closeout 见 [SPRINT2_DEDUP_PARITY_CLOSEOUT_20260521.md](./SPRINT2_DEDUP_PARITY_CLOSEOUT_20260521.md)；Sprint 3 local closeout 见 [SPRINT3_CLUB_SOURCE_CLOSEOUT_20260521.md](./SPRINT3_CLUB_SOURCE_CLOSEOUT_20260521.md)；去重与推文整合逻辑见 [DEDUP_SOURCE_INTEGRATION_LOGIC_20260521.md](./DEDUP_SOURCE_INTEGRATION_LOGIC_20260521.md)；票价/OCR 防线见 [PRICE_OCR_TICKETING_GUARD_20260521.md](./PRICE_OCR_TICKETING_GUARD_20260521.md)；`ping常` 双路线接手见 [PINGCHANG_TWO_ROUTE_HANDOFF_20260521.md](./PINGCHANG_TWO_ROUTE_HANDOFF_20260521.md)；文档/代码/计划生命周期审计见 [DOC_CODE_PLAN_SYNC_AUDIT_20260521.md](./DOC_CODE_PLAN_SYNC_AUDIT_20260521.md)。[NEXT_AGENT_HANDOFF_WEEKLY_MINIPROGRAM_FULL.md](./NEXT_AGENT_HANDOFF_WEEKLY_MINIPROGRAM_FULL.md) 是 2026-05-19 长版历史接手证据，不再作为当前数字入口。

## 一句话

当前线上 CloudRun 已更新为 `weekly-api-051`：后台资源包窗口 `2026-05-22..2026-06-05`，manifest/current `176`，远端分页拉全 `176/176`，旧日期 `<2026-05-22` 默认可见数为 `0`。本轮继续覆盖今天新增的 `Ping常`（2 条周活）和 `莫须有公社`（4 条周活），并修复“后端有但前端显示错/不显示”的兼容问题：`account_key` 保留原始账号 key，`account/promoter/source_account_name` 统一给旧前端可读显示名；`title_display` 不再把 `venue | date title`、`预告 5.29 title` 截成裸 venue/预告。materialized LLM 端点由本地 DeepSeek 脚本生成并随包发布，summary/enrichment `176/176`；CloudRun 只读缓存且无请求时 LLM 调用。10:12 复验确认 live manifest/current/source-action/materialized 可用，本地 source-map 已对齐已部署 `DISPLAY_COMPAT_0440` 包且 missing source-map URL 为 `0`；Release Guardian `GateMode=current-package` 仍因 latest queue summary 的 `exporter_refresh_requested=False` 记录缺口显示 `24/25`，这不是线上活动源加载故障。EXIT 票价仍为 `预售 70¥ / 双人 128¥ / 现场 100¥ / 3am 后免费入场`，不把 `3am` 显示成 `￥3`，也不发布 `预售 2026` / `DOOR 2026` 伪票价。小程序开发版仍是 `2026.05.21.2`，描述 `weekly-api-043-localLLM136-current136-resource-sync`；本轮 `weekly-api-051` 只更新后端/资源包，未上传新前端，微信提审未执行。`weekly-api-048` 是宿主默认 14 秒截断留下的 0% 流量版本，`weekly-api-050` 是被 r2 覆盖的中间候选，都不是当前线上。后续日常 OpenClaw 默认只更新后端/资源包：Docker exporter → 本地 OCR → 本地 LLM 物化 → 严格门禁 → CloudRun 部署；不上传前端、不提审，除非前端代码、权限、路由或不兼容 API schema 变化。新加坡服务器 / Singapore VPS 是炒股 beta 线，和周活小程序无关，不得用于小程序排障、部署、脚本/API 修复。

## 权威数字（勿混旧数据）

| 项 | 值 |
|----|-----|
| API | `weekly-api-051` |
| 条数 / 窗口 | manifest/current 176 / `2026-05-22..2026-06-05` |
| 小程序版 | `2026.05.21.2`（仍为最新开发版；本轮 051 未重新上传；未提审） |
| guardian 本地检查 | 10:12 `GateMode=current-package`：remoteTotal=176；live API/source-action/materialized 可用；source-map 已对齐，missingSourceMapUrl=0；mini_program_tests=40 pass |
| guardian 记录缺口 | `24/25` 通过；唯一失败项为 latest queue summary `exporter_refresh_requested=False`，属于队列溯源记录缺口，不是 current feed 加载故障 |
| strict 去重 | duplicate=0；effective_duplicate=0；conflict=0 |
| lineup/address/time | missing_lineup 136；address_diff=0；time_diff=0；hard_fail_count=0；missing_enrichment=0；enrichment=176/176 |
| 新账号同步 | `Ping常=2`；`莫须有公社=4`；display placeholder hits=0 |
| 当前日期清理 | 最早可见 `2026-05-22`；旧日期 `<2026-05-22` 默认可见 0；NUTS 三条月排期误范围已落到 5/23、5/24、5/29 |
| 票价防线 | `3am` 不转 `￥3`；year-like ticket hits=0；EXIT 5.22 分层票价远端详情已验证 |
| 显示兼容防线 | `account_key` 保留原 key；`account/promoter/source_account_name` 为显示名；标题不再被 source/date/time 段截断 |
| Golden | 88 条，20 conservative snapshot verified，68 pending |
| baseline drift | `snapshot_drift_count=43`（5/19 seed 对 5/21 current 的自然漂移） |
| atlas snapshot | 28,685 artist_profiles；209 lineup rows；alias_exact=63；fuzzy_multiple=90；no_match=56；exact-ID events 39/100（39%） |
| Sprint 2 parity | `weekly_dedup_spec.v1.json`；Python/mini-program/CloudRun parity PASS；frontend_extra_merge=0 |
| Sprint 2 source integration | duplicate source map redirect；retained event `merge_provenance`；temp current repair hard_fail=0 |
| Sprint 3 local UI/API | `organizer_key` + `club_profile` on current/detail/batch；detail/venue `SOURCE ARTICLES`；venue key match；city switchTab；venue/artist pagination；saved lang |
| 2026-05-21 source/date hotfix | static API `source_unavailable` 门禁；CloudRun/小程序静态兜底默认 current/date 隐藏已结束过去单日活动；先部署到 `weekly-api-042`，后被 `weekly-api-044`、`weekly-api-045` 覆盖继承；显式 date 查询保留 |
| 2026-05-21 CloudRun + 上传 | `weekly-api-043` deploy verified；production smoke ready；local DeepSeek materialized cache 136/136；CloudRun 无请求时 LLM；开发版 `2026.05.21.2` 上传 verified；未提审 |
| 2026-05-21 OCR/LLM/Atlas 审计 + 资源部署 | `weekly-api-044` deploy verified；production smoke ready；EXIT 票价误判修复；5/20 默认可见 0；Atlas snapshot/observations 已打入 CloudRun context；当前 LLM coverage 缺失 0；未上传前端、未提审 |
| 2026-05-21 23:10 后台 current 包刷新 | `weekly-api-045` deploy verified；production smoke ready；默认 current `127`；5/20 默认可见 0；本地 LLM materialized `127/127`；DevTools 首页加载 4.36s 且 8 步交互通过；未上传前端、未提审 |
| 2026-05-22 03:51 MoXu/Ping 后端资源同步 + 日期修复 | `weekly-api-049` deploy verified；production smoke ready；默认 current `177`；最早可见日期 `2026-05-22`；Ping常 2；莫须有公社 4；本地 LLM materialized `177/177`；EXIT 票价/年份伪票价修复；NUTS 月排期 stale date 修复；未上传前端、未提审；已被 05:02 `weekly-api-051` 覆盖 |
| 2026-05-22 05:02 显示兼容修复 + 后端资源同步 | `weekly-api-051` deploy verified；production smoke ready；默认 current `176`；最早可见日期 `2026-05-22`；Ping常 2；莫须有公社 4；本地 LLM materialized `176/176`；promoter/account 裸 key 修复；title_display 截断修复；未上传前端、未提审 |
| 2026-05-21 日常发布策略 | 定时任务默认后端/资源包-only；本地 OCR + 本地 LLM 生成物化缓存；CloudRun 只读缓存；小程序前端上传必须显式 `-UploadFrontend` 且有前端/权限/路由/schema 理由；提审另走 guarded executor |
| 2026-05-21 服务器边界 | 新加坡服务器 / Singapore VPS = 炒股 beta 线；不属于周活小程序 / Atlas 只读联动 / CloudRun weekly-api / Docker exporter / 小程序上传链 |

## Sprint 1 新增/修正代码（已验证）

```
tools/stage7_rewrite/
  scripts/weekly_golden_lib.py
  scripts/bootstrap_weekly_golden_set.py
  scripts/evaluate_weekly_golden_baseline.py
  scripts/verify_weekly_golden_s1.py
  scripts/build_weekly_atlas_snapshot.py
  scripts/export_weekly_entity_observations.py
  weekly_atlas_bridge/          # resolver + snapshot + observations
  golden/golden_set_v1.jsonl
  tests/test_weekly_golden_baseline.py
  tests/test_verify_weekly_golden_s1.py
  weekly_atlas_bridge/tests/test_resolver.py
```

验证：guardian ok=true；strict duplicate/conflict 0/0/0；Python targeted **47/47 OK**；小程序 Node **29/29 OK**。

## Sprint 2 parity 新增/修正代码（已验证）

```
tools/stage7_rewrite/fixtures/weekly_dedup_spec.v1.json
tools/stage7_rewrite/tests/test_weekly_dedup_spec_parity.py
apps/weekly_activity_miniprogram/tests/dedup-parity.test.cjs
apps/weekly_activity_miniprogram/utils/format.js
services/weekly_activity_cloudrun/tests/dedupParity.test.mjs
services/weekly_activity_cloudrun/src/dataStore.mjs
```

验证：Python L2 parity + repair conflict **10/10 OK**；小程序 Node **30/30 pass**；CloudRun Node **38/38 pass**；当前 158 包 strict duplicate/conflict **0/0/0**。

## Sprint 2 推文整合新增/修正代码（已验证）

```
tools/stage7_rewrite/scripts/repair_weekly_release_conflicts.py
tools/stage7_rewrite/tests/test_repair_weekly_release_conflicts.py
docs/weekly-miniprogram-handoff-20260519/DEDUP_SOURCE_INTEGRATION_LOGIC_20260521.md
docs/weekly-miniprogram-handoff-20260519/SPRINT2_SOURCE_INTEGRATION_CLOSEOUT_20260521.md
```

验证：重复合并会在 retained event 写 `merge_provenance`；被合并 source map 条目 redirect 到 retained event；当前 158 包临时 repair 后 `missing_lineup=58`、`hard_fail=0`。

## Sprint 3 小程序/Atlas 交叉本地切片（已验证）

```
apps/weekly_activity_miniprogram/utils/format.js
apps/weekly_activity_miniprogram/utils/sourceArticles.js
apps/weekly_activity_miniprogram/pages/detail/detail.js
apps/weekly_activity_miniprogram/pages/detail/detail.wxml
apps/weekly_activity_miniprogram/pages/detail/detail.wxss
apps/weekly_activity_miniprogram/pages/venue/venue.js
apps/weekly_activity_miniprogram/pages/artist/artist.js
apps/weekly_activity_miniprogram/pages/city/city.js
apps/weekly_activity_miniprogram/pages/index/index.js
apps/weekly_activity_miniprogram/pages/saved/saved.js
services/weekly_activity_cloudrun/src/dataStore.mjs
services/weekly_activity_cloudrun/tests/weeklyApi.test.mjs
apps/weekly_activity_miniprogram/tests/source-articles.test.cjs
apps/weekly_activity_miniprogram/tests/page-source-routing.test.cjs
apps/weekly_activity_miniprogram/tests/format-quality.test.cjs
```

验证：CloudRun API tests **30/30 pass**；CloudRun full tests **39/39 pass**；mini-program non-DevTools CJS/static tests pass；`stage7_safe_handoff_verify.ps1` **PASS**（Python targeted **354 passed**，CloudRun Stage7 **39 pass**）；当前 158 包 strict duplicate/effective/conflict **0/0/0**；Release Guardian `GateMode=current-package` **ok=true**，默认 `GateMode=release` 因 exporter effective freshness 失败保持阻断。DevTools 真机/上传未执行。

## 票价 / OCR 防线更新（2026-05-21）

问题：EXIT 截图原文为 `3am 后免费入场`，旧抽取链会把 `3am` 的 `3` 误读成 `￥ 3`，同时漏掉 `预售 70￥ / 双人 128￥ / 现场 100￥` 的后缀金额。

已修正：上游 exporter pack、Stage7 recommendation pack、static API、DeepSeek/CloudRun prompt、小程序 `format.js` 都加入同一条规则：`3am/3 AM/凌晨3点` 是时间条件，不是价格；`3am 后免费入场` 必须作为完整入场规则保留。新公众号 `Ping常` 已解析 fakeid/city 并切入 active staging；`weekly_accounts_seed.json` 记录 79/79 同步，`weekly_venues_seed.json` 记录杭州 BAC 地址。

验证：Python targeted **60/60 OK**；mini-program format **13/13 OK**；registry validate ok=true；`py_compile` PASS；`git diff --check` PASS（仅 LF/CRLF 提示）。该票价/OCR 切片当时未执行 CloudRun 新部署、小程序上传或微信提审；后续 `19:04` 仅执行了 CloudRun 部署。

## Ping常 双路线接手（2026-05-21）

入口：[PINGCHANG_TWO_ROUTE_HANDOFF_20260521.md](./PINGCHANG_TWO_ROUTE_HANDOFF_20260521.md)。

已做：

- Docker exporter 重新登录后，脚本已自动发现最新 `.mptext-data\kv\cookie` key；`diagnose_weekly_exporter_session.py --auth-source auto` 通过。
- `Ping常` 已解析 fakeid `Mzg5NDk3Mjc0MA==`，注册表状态为 active staging；杭州 BAC 地址已写入 venue registry。
- 历史 URL 拉取完成：`pagesFetched=4`、`uniqueUrlCount=79`，输出在 `D:\downstream_results\stage7_rewrite\longrun\PINGCHANG_HISTORY_20260521\history_full_auto_key\history_Ping常`。
- 新规则周活 staging v2 发布候选 2 条：`2026-05-22 Ping常｜5.22 周五｜白X3`、`2026-05-23 Ping常｜5.23 周六｜Kchen`；strict duplicate/effective/conflict `0/0/0`，source-data audit `ok=true`。
- 老路线 Atlas staging 已跑到 archive/process/assets/OCR evidence：20 valid archive、59 partial retry；poster OCR backend=`none`，本进程缺 LLM key，未进入 downstream LLM/Atlas production 写入。
- 多日排期拆分已修正：标题 `5.20-23` 不再盖掉正文 `5.22/5.23` 子日期段，父排期文不直接重复发卡。

后续：若再出现 `ret=200003 invalid session`，先按登录态 4 天过期处理，重新登录 Docker exporter 后复跑 auto diagnostic；不要手工打印或复制 key。

## 原文删除 / 5.20 默认展示修正（2026-05-21 18:28）

问题 1：原文链接被删除时，旧构建链只检查 `source_url` 是否存在，仍可能把 stale URL 对应活动写入 `current.json` 和 `source_url_map.json`。

已修正：`build_weekly_activity_miniprogram_api.py` 新增 `source_unavailable` 发布门禁，识别删除布尔字段、不可用 status、`404/410`、删除/不存在错误文本，并支持 `--deleted-source-registry` 用 URL 或 `url_hash` 手动阻断。被阻断行不会进入活动卡或 source map。

问题 2：5.21 默认首页仍显示 5.20 活动。根因不是清理脚本，而是 158 包窗口为 `2026-05-20..2026-06-03`，CloudRun `getCurrent()` 和小程序静态兜底在没有显式 date 时都把它当成“不过滤日期”。

已修正：默认 current 只显示今天及以后，或仍在进行中的多日活动；date chips 默认隐藏过去日期。显式 `date=2026-05-20` 仍保留，用于直接回查/调试。

验证：Python static API tests **34/34 OK**；mini-program static fallback **13/13 pass**；CloudRun weekly API **32/32 pass**；`npx tsc -p tsconfig.json --noEmit` PASS；mini-program format/source/static Node checks **18/18 pass**。

## CloudRun + 小程序上传闭环（2026-05-21 20:32）

已执行：最新资源包 + CloudRun `weekly-api-043` 后端部署 + 小程序开发版上传。部署报告 `tools\stage7_rewrite\reports\cloudrun_direct_deploy_weekly_upload_20260521_043\cloudrun_direct_api_deploy_report.json` 为 `cloudrun_direct_api_deploy_verified`；资源包 zip `133,246,831` bytes / `373` files；生产 smoke `tools\stage7_rewrite\reports\cloudrun_weekly_production_smoke_upload_20260521_043\cloudrun_weekly_production_smoke.json` 为 `cloudrun_weekly_production_smoke_ready`，blockers `[]`。小程序上传报告 `tools\stage7_rewrite\reports\miniprogram_upload_20260521_2\miniprogram_upload_execution_report.json` 为 `miniprogram_developer_version_upload_verified`，开发版本 `2026.05.21.2`，上传包 buffer `513583` bytes，code files `34`。

远端事实：manifest `158`；默认 `/api/v1/weekly/current?limit=100` 的 `page.total=136`；物化 LLM 端点为本地脚本生成的 DeepSeek Pro 缓存：summary/enrichment `136/136`。Release Guardian `GateMode=current-package` 为 `ok=true`，remoteTotal `136`，backend raw URL/CDN hits `0`，visible hits `0`，source map missing `0/0`。

提审边界：`tools\stage7_rewrite\reports\miniprogram_review_submission_boundary_20260521_2\miniprogram_review_submission_boundary.json` 记录当前本地 `miniprogram-ci@2.1.31` 无 submit-review 命令；本次 `review_submitted=false`。若要自动提审，需要另建 guarded 微信审核 API executor，不能把开发版上传等同于提审。

未执行：微信提审、Atlas production 写入、Neo4j/Qdrant/production SQLite 写入、OCR 抽取、付费 Dajiala、CloudRun 请求时 LLM、secret/cookie 打印、新加坡服务器访问。

日常策略：这次 `2026.05.21.2` 是一次显式开发版上传闭环，不代表每日都要上传前端。后续定时任务默认只更新资源包/后端并做 smoke/guardian；只要小程序代码、权限、路由和接口兼容层没变，用户端通过同一个 CloudRun API 获取新资源，不需要微信审核。

## CloudRun 部署闭环（2026-05-21 19:50，已被 20:32 覆盖）

已执行：本地 DeepSeek LLM 物化 + CloudRun `weekly-api-042` 部署。该状态已被上方 `weekly-api-043` 覆盖。部署报告 `tools\stage7_rewrite\reports\cloudrun_direct_deploy_weekly_date_hotfix_local_llm_20260521\cloudrun_direct_api_deploy_report.json` 为 `cloudrun_direct_api_deploy_verified`；生产 smoke `tools\stage7_rewrite\reports\cloudrun_weekly_production_smoke_weekly_date_hotfix_local_llm_20260521\cloudrun_weekly_production_smoke.json` 为 `cloudrun_weekly_production_smoke_ready`，blockers `[]`。

远端事实：manifest `158`；默认 `/api/v1/weekly/current?limit=100` 的 `page.total=136`，首条日期 `2026-05-21`；`/api/v1/weekly/dates` 不含 `2026-05-20`；显式 `date=2026-05-20` 回查 `26` 条。物化 LLM 端点为本地脚本生成的 DeepSeek Pro 缓存：`provider=deepseek`、`model=deepseek-v4-pro`、`thinking=disabled`、`timeoutMs=null`、summary/enrichment `136/136`。CloudRun `/api/v1/weekly/llm/status` 显示 `configured=false`、`timeoutDisabled=true`，表示线上请求不会现场调用 LLM。

该 19:50 切片未执行：小程序新上传、微信提审、Atlas production 写入、Neo4j/Qdrant/production SQLite 写入、OCR 抽取、付费 Dajiala、CloudRun 请求时 LLM、secret/cookie 打印。20:32 切片后来补做了开发版上传，但仍未提审。

## 下一 agent 三件事

1. 修复/重新授权 daily queue exporter session，再复跑默认 release guardian；不要把 `GateMode=release ok=false` 误判为本地 158 包去重失败
2. 等待/生成下一次 OpenClaw 新包后，复跑 repair + strict audit，确认 source provenance 不丢、去重不新增重复卡；默认只部署 CloudRun 后端/资源包，不上传前端
3. 处理 baseline drift：决定是否基于当前 158 包刷新/版本化 Golden；20 verified 不是人工/inter-annotator 金标
4. Sprint 4 需要 G0 alias export/new snapshot；开发版已上传 `2026.05.21.2`，提审仍需单独 guarded executor/批准

## 边界

小程序 ≠ 图谱；向量不进展示；不写 Neo4j/Qdrant production；新加坡服务器 ≠ 小程序运行/部署资源（它是炒股 beta 线）；日常 OpenClaw 默认后端/资源包-only；本次已做 CloudRun 后端/资源包部署和一次显式小程序开发版上传，未执行微信提审。
