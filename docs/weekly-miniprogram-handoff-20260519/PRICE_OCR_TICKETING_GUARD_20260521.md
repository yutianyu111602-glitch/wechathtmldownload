# 票价 / OCR 入场规则防线 — 2026-05-21

Scope: 周活小程序发布管线、本地静态 API、CloudRun/DeepSeek 提示词、前端显示兜底。

## 结论

截图原文是 `预售 70￥ / 双人 128￥ / 现场 100￥ / 3am 后免费入场`。错误显示成 `￥ 3 / 免费入场` 的根因不是小程序详情页单独渲染问题，而是 OCR/文本抽取后的票价正则把 `3am` 里的 `3` 当成了金额，同时丢掉了后缀金额格式 `70￥/128￥/100￥` 的上下文。

## 当前规则

- `3am`、`3 AM`、`凌晨3点` 是时间条件，不是价格。
- `3am 后免费入场` 这类内容必须作为完整入场规则保留，不能拆成 `￥3` + `免费入场`。
- 上游抽取要支持后缀金额：`预售 70￥`、`双人 128￥`、`现场 100￥`。
- 票价标签不得跨段落/证据行吞掉下一行日期；`预售\n2026-05-22` 不能变成 `预售 2026`。
- 裸 `19xx/20xx` 年份不是票价；无货币符号的 `预售 2026` / `DOOR 2026` / `现场 2026` 必须丢弃。
- 静态 API 和小程序前端都有兜底清洗：如果旧包仍含 `￥ 3` + `免费入场`，且证据/票务文本出现 `3am 后免费入场`，展示为完整入场规则。
- LLM 提示词明确约束：票价必须逐字来自正文/OCR，时间条件不能倒推出金额。

## 改动范围

| 层 | 文件 | 作用 |
|----|------|------|
| exporter queue pack | `tools/stage7_rewrite/scripts/archive_old/build_weekly_activity_pack_from_exporter_queue.py` | 票价正则支持后缀金额；拒绝 `￥3am` 变 `￥3` |
| Stage7 recommendation pack | `tools/stage7_rewrite/scripts/archive_old/build_weekly_activity_recommendation_pack.py` | 同步票价正则，保护 L1/L2 输入 |
| static API | `tools/stage7_rewrite/scripts/archive_old/build_weekly_activity_miniprogram_api.py` | `clean_price_items()` 发布前清洗旧污染 |
| DeepSeek prompt | `tools/stage7_rewrite/scripts/enrich_weekly_activity_pack_with_deepseek.py` | 加入 3am/凌晨3点非票价规则 |
| CloudRun prompt | `services/weekly_activity_cloudrun/src/llmEnrichment.mjs` | 同步运行时抽取约束 |
| mini-program display | `apps/weekly_activity_miniprogram/utils/format.js` | 旧包前端兜底，不显示 `￥ 3 / 免费入场` |
| account/venue registry | `tools/stage7_rewrite/registries/weekly_accounts_seed.json`, `tools/stage7_rewrite/registries/weekly_venues_seed.json` | `Ping常` 已解析 fakeid/city 并进入 active staging；杭州 BAC 地址进入 venue registry |
| schedule split | `tools/stage7_rewrite/scripts/archive_old/build_weekly_activity_pack_from_exporter_queue.py` | 标题范围 `5.20-23` 不再盖掉正文 `5.22/5.23` 子日期段；父排期文不重复发卡 |

## 验证

- Python targeted: `60 tests OK`
- Mini-program Node format quality: `13 tests OK`
- `py_compile`: PASS
- weekly account registry validate: `ok=true, error_count=0, warning_count=0`
- `git diff --check`: PASS（仅既有 LF/CRLF 提示）
- Ping常 staging v2: API `item_count=2`，strict duplicate/effective/conflict `0/0/0`，source-data audit `ok=true`，无 `￥3` 污染。

## 2026-05-22 策略评测补充

- DeepSeek 本地矩阵完成 `600/600` 调用；生产物化仍选 `yellowpage_gate_v3 + deepseek-v4-flash + thinking disabled + temperature 0.0/0.1`。
- 票务 10 个确定证据样本：current package exact `3/10`，`source_regex_conservative` exact `10/10`，DeepSeek strict tiers `16/20`。
- 结论：票价字段以原文/OCR 确定性正则为发布权威；LLM 只能输出候选/复核，不得把 QR/芋圆/小程序码、酒水优惠、3am 时间条件提升为门票价格。
- `build_weekly_activity_miniprogram_api.py` 新增只读 `--source-queue`，在 recommendation evidence 被截断时从最新下载队列 digest/body 补源给票务抽取。Local probe 已恢复 EXIT 5.22/5.23 的 `预售/双人/现场/3am 后免费入场`；未部署。
- 证据：`reports\WEEKLY_INFO_SQUEEZE_STRATEGY_EVAL_20260521.md`。

## 2026-05-22 03:17 后端同步补充

- 当前远端已部署 `weekly-api-047`，manifest/current `177`，materialized LLM `177/177`。
- EXIT 5.22 远端详情已验证为 `预售 70¥ / 双人 128¥ / 现场 100¥ / 3am 后免费入场`，无 `￥3`，无 `预售 2026`。
- 候选包补丁清理了 `15` 个静态 JSON 路由文件中的 `24` 个年份伪票价字段。
- 远端全量 current 检查：year-like ticket hits `0`，display placeholder hits `0`。
- 证据：`reports\WEEKLY_MOXU_PING_BACKEND_SYNC_20260522.md`，补丁报告 `tools\stage7_rewrite\reports\openclaw_weekly_daily_20260522_024025\price_ticketing_patch_report.json`。

## 边界

2026-05-22 03:17 已执行 CloudRun 后端/资源包部署到 `weekly-api-047`。未上传小程序前端、未提交微信审核、未执行 Atlas 生产写入、Neo4j/Qdrant 写入或新加坡服务器操作。新增 `--source-queue`、跨行票价防线和年份伪票价防线会保护下一次 rebuild，并让小程序前端对已存在旧包有显示兜底。
