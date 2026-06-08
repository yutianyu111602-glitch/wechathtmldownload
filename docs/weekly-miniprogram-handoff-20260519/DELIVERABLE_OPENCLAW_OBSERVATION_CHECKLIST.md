# 交付物：OpenClaw 日更 24h 观测清单

Updated: 2026-05-19

## 1. 自动化真相

| 层 | 事实 |
|----|------|
| Windows 权威入口 | `tools\stage7_rewrite\run_openclaw_weekly_daily_publish.ps1` |
| Linux cron（文档） | 09:30 `huaidj-daily-download.sh`；12:30 `huaidj-weekly-openclaw-stable.sh` |
| 缺口 | cron **未必**已切新 ps1；**首跑未观测** |
| 12:30 默认 | deploy + reconcile；**默认不上传小程序** |

## 2. 观测时间窗

- T0：cron 前 5 分钟
- T+30min：构建/validator
- T+90min：deploy + reconcile
- T+24h：queue 再刷新

## 3. 检查表

### 阶段 1 — 队列

| # | 项 | 通过标准 |
|---|-----|----------|
| 1 | latest_queue.jsonl | 存在、非空 |
| 2 | 新鲜度 | age ≤ 72h（实测 7.8h） |
| 3 | summary.json | rows_written>0 |

### 阶段 2 — 构建

| # | 项 | 通过标准 |
|---|-----|----------|
| 5 | API 目录 | WEEKLY_ACTIVITY_MINIPROGRAM_API_YYYYMMDD |
| 6 | 条数 | ≥ 80 |
| 7–9 | 严格门 | duplicate/conflict/lineup audit = 0 |
| 10 | backendRawHits | **建议 0**（当前 51） |
| 11 | materialized | enrichment 条数 = current |

### 阶段 3 — 部署

| # | 项 | 通过标准 |
|---|-----|----------|
| 12 | deploy 报告 | reports/cloudrun_direct_deploy_* |
| 13 | WinError 10054 | 重试 1 次 |
| 14 | 劣化包 | 未过门不覆盖 |
| 15–17 | 远端 | total≥80；103/103 reconcile |

### 阶段 4 — 小程序（仅 -UploadFrontend）

| # | 项 | 通过标准 |
|---|-----|----------|
| 18 | 单测 | 24 pass |
| 19 | guardian | ok, visibleHits=0 |
| 20–21 | 上传/提审 | 记录版本；提审人工 |

### 阶段 5 — 产物

| # | 项 | 通过标准 |
|---|-----|----------|
| 22 | openclaw summary JSON | ok=true |
| 23 | cron 日志 | 无未处理 exception |
| 24 | cron↔wrapper | **待确认** stable.sh 调用链 |

## 4. 失败分级

| 级别 | 示例 | 动作 |
|------|------|------|
| P0 | reconcile 不齐、条数骤降>20% | 停止 deploy；不上传 |
| P1 | backendRawHits>0 | 可 deploy，记债 |
| P2 | 单测失败 | 阻塞 upload |

## 5. 观测记录模板

```yaml
observed_at:
cron_script:
queue_age_hours:
api_dir:
item_count:
backend_raw_url_hits:
remote_service:
remote_total:
reconcile_missing_extra:
miniprogram_uploaded:
dev_version:
blockers: []
```

## 6. 分页 reconcile 命令

```powershell
$base="https://weekly-api-255880-4-1371956557.sh.run.tcloudbase.com"
$all=@(); $cursor="0"
do {
  $r=Invoke-RestMethod -Uri "$base/api/v1/weekly/current?limit=100&cursor=$cursor" -TimeoutSec 30
  $all+=$r.items
  $cursor=if($r.page){$r.page.nextCursor}else{$null}
} while($cursor)
$idx=Invoke-RestMethod -Uri "$base/api/v1/weekly/llm/materialized-enrichments" -TimeoutSec 30
# 对比 $all.id 与 $idx.enrichments.id
```
