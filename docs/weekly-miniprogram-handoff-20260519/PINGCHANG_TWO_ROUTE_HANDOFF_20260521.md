# Ping常 双路线接手记录 — 2026-05-21

## 当前结论

`Ping常` 已在用户重新登录 Docker exporter 后解析成功，并已进入周活账号/场馆注册表的 active staging 口径。本次完成两条路线：

- 老抽取路线：历史 URL 已拉下，archive/process/assets/OCR staging 已跑；Atlas production 未写入。
- 新规则路线：本周活动已从同一篇多日排期推文拆成 2 条可发布 staging item；去重/source audit 通过。

关键边界：没有 CloudRun deploy、小程序 upload/review、Neo4j/Qdrant/production SQLite 写入、付费 LLM 调用、cookie/key 明文输出。

## Docker 登录态 / mptext API 规则

本次阻塞根因是 `MPTEXT_AUTH_KEY` 环境变量仍存在但已失效，mptext 返回 `ret=200003 invalid session`。用户已重新登录 Docker exporter；新的可用 key 在 Docker 挂载目录 `.mptext-data\kv\cookie` 中体现为最新的 32-hex 文件名。

已落地的体系：

- `src/mptext/client.ts` 默认自动发现最新 Docker cookie key。
- `MPTEXT_AUTH_KEY_PREFER_ENV=1` 时才强制优先使用环境变量。
- Python 诊断/周更队列也支持 `auto` 发现，并只报告来源和 hash，不打印 key。
- 以后如果看到 `ret=200003 invalid session`，优先判断为登录态过期；重新登录后不需要手工复制 key，脚本会取最新 Docker cookie key。

诊断通过：

```powershell
python tools\stage7_rewrite\scripts\diagnose_weekly_exporter_session.py `
  --auth-source auto `
  --out D:\downstream_results\stage7_rewrite\longrun\PINGCHANG_HISTORY_20260521\diagnostics\exporter_session_auto_key_20260521.json
```

结果：`decision=exporter_session_ok`，`session_ok=true`，`auth_source=docker-data`，`ret=0`。

## 账号与场馆注册

账号注册表：`tools/stage7_rewrite/registries/weekly_accounts_seed.json`

- `account_id`: `pingchang`
- `account_name`: `Ping常`
- `fakeid`: `Mzg5NDk3Mjc0MA==`
- `city_key`: `hangzhou`
- `type`: `club`
- `status`: `active`
- `export_synced_count`: `79`
- `export_total_count`: `79`

场馆注册表：`tools/stage7_rewrite/registries/weekly_venues_seed.json`

- `venue_key`: `ping_hangzhou`
- `canonical_name`: `Ping常`
- `city_key`: `hangzhou`
- `address`: `杭州市西湖区转塘街道美院南街BAC艺术社区A-109-4`
- default time：`22:00 - Late`

## 历史推文拉取

命令：

```powershell
npx tsx src\historyCli.ts `
  --provider mptext `
  --url "ping常" `
  --outDir D:\downstream_results\stage7_rewrite\longrun\PINGCHANG_HISTORY_20260521\history_full_auto_key `
  --maxPages 400
```

结果：

- 输出目录：`D:\downstream_results\stage7_rewrite\longrun\PINGCHANG_HISTORY_20260521\history_full_auto_key\history_Ping常`
- `pagesFetched=4`
- `uniqueUrlCount=79`
- `stoppedReason=no-more-items`
- queue：`archive_queue.jsonl`

## 路线 1：老抽取路线 → Atlas staging

已跑到本地 staging，不进入 Atlas production。

| 阶段 | 输出 | 结果 |
|------|------|------|
| mptext archive | `...\old_route_archive_mptext` | 79 total；20 valid；59 partial/invalid raw.html |
| archive audit | `...\old_route_archive_audit` | retry_queue 59；issue `invalid_raw_html=59` |
| asset retention | `...\old_route_archive_assets` | 20 succeeded；59 failed because archive partial |
| process with assets | `...\old_route_process_with_assets` | 79 completed；20 used local assets；59 partial rows carry weak/empty content |
| poster OCR | `...\old_route_poster_ocr` | 60 rows completed but backend=`none`，没有真实 OCR 文本 |

当前阻塞：

- 本进程没有 OpenAI-compatible API key 环境变量，`run-downstream-llm-batch` 未启动。
- poster OCR backend 为 `none`，不能把 OCR 结果当成事实。
- 59 条 archive partial 需要后续 retry，不能直接进 Atlas candidate pack。

下一步只允许做 staging：

1. 补齐 OCR/LLM runtime 后，只对 20 条 valid archive 先跑 canary。
2. 输出 graph candidate pack + `ignuke-dry-run-import`。
3. 任何 Neo4j/Qdrant/production SQLite 写入必须另行审批。

## 路线 2：新规则抽取本周活动

队列输入：

```powershell
python tools\stage7_rewrite\scripts\build_weekly_activity_queue_from_downloads.py `
  --accounts pingchang `
  --refresh-from-exporter `
  --articles-per-account 120 `
  --body-backfill `
  --body-backfill-since-date 2026-05-14 `
  --body-backfill-until-date 2026-05-27 `
  --out-dir D:\downstream_results\stage7_rewrite\longrun\PINGCHANG_HISTORY_20260521\weekly_new_rules_queue_after_relogin
```

queue 结果：

- `accounts_requested=1`
- `exporter_accounts_ok=1`
- `exporter_accounts_failed=0`
- `exporter_article_rows=79`
- `rows_written=79`
- `account_counts.pingchang=79`
- exporter/body backfill auth source: `docker-data`

多日排期拆分修正：

旧逻辑优先吃标题里的 `5.20-23`，会把正文里的 `5.22 周五 / 5.23 周六` 明细盖掉。现在 `build_weekly_activity_pack_from_exporter_queue.py` 会识别同一篇推文里的日期段落：

- `📅5.20 周三｜黑胶夜`
- `📅5.22 周五｜白X3`
- `📅5.23 周六｜Kchen`

并拆成同源 child event，保留相同 source URL/hash，避免父排期文重复发卡。

pack/API v2 输出：

- pack：`D:\downstream_results\stage7_rewrite\longrun\PINGCHANG_HISTORY_20260521\weekly_new_rules_pack_after_relogin_v2`
- API：`D:\downstream_results\stage7_rewrite\longrun\PINGCHANG_HISTORY_20260521\weekly_new_rules_api_after_relogin_v2`
- `weekly_queue_total=79`
- `candidates=103`
- `review_candidates=32`
- `high_confidence_candidates=17`
- API `item_count=2`

当前 2026-05-21..2026-05-27 staging item：

| 日期 | 标题 | 时间 | lineup | 票价 |
|------|------|------|--------|------|
| 2026-05-22 | `Ping常｜5.22 周五｜白X3` | `22:00 - Late` | `白X3` | 空 |
| 2026-05-23 | `Ping常｜5.23 周六｜Kchen` | `22:00 - Late` | `Kchen` | 空 |

去重与 source audit：

- strict duplicate/effective/conflict: `0/0/0`
- source-data strict audit: `ok=true`
- visible raw URL hits: `0`
- qpic hits in description/bio text: `0`
- 未发现 `3am` 被当作 `￥3` 的污染。

## 价格 / OCR 结论

EXIT 截图里的 `3am 后免费入场` 是时间条件，不是 `3 元门票`。本次代码与测试已经覆盖：

- `预售 70￥ / 双人 128￥ / 现场 100￥` 后缀金额可识别。
- `3am 后免费入场` 作为完整入场规则保留。
- 小程序前端不会显示 `￥ 3 / 免费入场` 的旧污染组合。

## 已验证命令

```powershell
python -m unittest tools.stage7_rewrite.tests.test_weekly_activity_exporter_queue_pack tools.stage7_rewrite.tests.test_diagnose_weekly_exporter_session -v
npx tsc -p tsconfig.json --noEmit
node --test apps\weekly_activity_miniprogram\tests\format-quality.test.cjs
python -m unittest tools.stage7_rewrite.tests.test_weekly_registries -v
python -m unittest tools.stage7_rewrite.tests.test_weekly_activity_miniprogram_api -v
python tools\stage7_rewrite\scripts\audit_weekly_cross_source_conflicts.py --input D:\downstream_results\stage7_rewrite\longrun\PINGCHANG_HISTORY_20260521\weekly_new_rules_api_after_relogin_v2\current.json --strict --fail-on-raw-duplicates
python tools\stage7_rewrite\scripts\audit_weekly_source_data_compare.py --api-dir D:\downstream_results\stage7_rewrite\longrun\PINGCHANG_HISTORY_20260521\weekly_new_rules_api_after_relogin_v2 --pack-dir D:\downstream_results\stage7_rewrite\longrun\PINGCHANG_HISTORY_20260521\weekly_new_rules_pack_after_relogin_v2 --window-start 2026-05-21 --window-days 7 --venue-registry tools\stage7_rewrite\registries\weekly_venues_seed.json --account-registry tools\stage7_rewrite\registries\weekly_accounts_seed.json --report D:\downstream_results\stage7_rewrite\longrun\PINGCHANG_HISTORY_20260521\weekly_new_rules_api_after_relogin_v2\source_data_compare.json --strict
```

## 安全边界

本次没有执行 CloudRun deploy、小程序 upload/review、微信提审、Neo4j/Qdrant/production SQLite 写入、LLM 在线抽取、付费 Dajiala、浏览器 credential-store 读取、cookie/token/key 明文输出、D 盘根扫描或 9router 探测。
