# OpenClaw / DB2 外链抓取接手报告 - 2026-06-03

## 1. 主问题

下一位 DB2/OpenClaw agent 需要从最新 no-execution / fail-closed 控制面继续接手：消费 weekly/source-fetch disposition queue 和现有 DB2 loop-state，不要自行恢复 Docker/worker/crawl/network/DB/DeepSeek/package/CloudBase/upload/release。

## 1.1 本线程职责

这条 Codex 线程是 DB2/OpenClaw 外链抓取、武器库和控制面自循环的接手整理线程。它不是 weekly 小程序前端 hotfix 线程，不是 CloudBase 上传/发布线程，也不是 Docker worker 生产执行线程。

本线程的核心职责：

- 维护 DB2/OpenClaw 的当前事实口径：哪些 artifact 已消费、哪些 gate 仍关闭、哪些字段证明 runtime 不允许。
- 把外链抓取上下游、source-fetch 12 行链路、武器库候选、Docker/container 分层方向写成后续 agent 可直接执行的接手说明。
- 在主控没有 explicit controller gate 时保持 fail-closed，防止后续 agent 误启动 Docker/worker/crawl/network/DB/DeepSeek/API/package/CloudBase/upload/release。
- 记录 WSL2 DeepSeek TUI 只是研究/侧车/提示生成入口，不是 DB2 controller release 来源。

本线程当前结论：

- DB2/OpenClaw 长期方向仍是分层 Docker/container worker/runtime。
- skill/db2ctl 只做薄控制面：artifact 消费、parser、status packet、loop/wake decision、contract/preflight/report-only verification。
- 当前可接手的最新 DB2/source-fetch 入口是 disposition queue，而不是 runtime 继续执行。
- 下一步必须等待 `manual_source_evidence_acceptance`、`accepted_no_fetch_disposition` 或 `explicit_authenticated_source_cache_release`；不能横向扩展到 DB/CloudBase/upload/release。

## 2. 范围

- 主仓：`C:\code\githubstar\wechathtmldownload`。
- DB2 worktree：`C:\code\.worktrees\wechathtmldownload\20260601-db2-weapons-containers`。
- DB2 branch：`codex/wechathtmldownload-db2-weapons-containers`。
- 当前 DB2 HEAD：`e68364c Wire OpenClaw approval status into wake loop`。
- 本报告覆盖：
  - DB2/OpenClaw 外链抓取上下游规则。
  - source-fetch L2 gate 链和当前 disposition queue。
  - weapons/工具库选择规则。
  - fail-closed/no-execution 边界。
- 本报告不释放 runtime，不创建 controller approval，不跑生产管线。

## 3. 当前状态摘要

### DB2/OpenClaw loop-state

最新 worktree report：

- `tools/stage7_rewrite/reports/db2_openclaw_loop_state_latest.json`
- `tools/stage7_rewrite/reports/db2_openclaw_wake_decision_latest.json`
- `tools/stage7_rewrite/reports/db2_openclaw_direct_deepseek_controller_approval_status_latest.json`

已证实字段：

- `controller_approval_required=true`
- `controller_approval_present=false`
- `runtime_start_gate_released=false`
- `runtime_execution_allowed_now=false`
- `next_action=wait_for_explicit_controller_approval_for_runtime_execution`
- `would_execute=false`
- `would_start_docker=false`
- `would_call_network_or_deepseek=false`
- `would_call_deepseek=false`
- `would_write=false`
- `would_write_live_db=false`
- `would_read_credentials=false`
- `would_rebuild_package=false`
- `would_upload_or_release=false`

这意味着 DB2/OpenClaw 当前仍是 fail-closed 等待态。

### 工作树状态

DB2 worktree 当前不是干净状态，存在大量既有 dirty/untracked 文件。不要清理、reset、checkout、git clean。尤其注意未提交的 `iteration-062` 草稿和 `db2ctl.py`/`test_db2ctl.py` 修改，之前已被主控要求暂停，不要继续除非用户明确重开 DB2 控制面。

## 4. Source-fetch 最新 gate 链

主仓本轮 weekly 坐标 source-fetch 已走到 `disposition_queue`，不是 deploy/upload/release。

### 4.1 Worker contract

路径：

- `tools/stage7_rewrite/reports/weekly_current_missing_geo_source_fetch_worker_contract_20260603/weekly_current_missing_geo_source_fetch_worker_contract.json`
- `reports/WEEKLY_CURRENT_MISSING_GEO_SOURCE_FETCH_WORKER_CONTRACT_20260603.md`

口径：

- Layer：`L2_SOURCE_EVIDENCE_FETCH`
- Docker profile：`openclaw-source-queue-cache`
- Queue：`weekly_current_missing_geo_source_fetch_20260603`
- 仅 no-execution contract evidence。
- Docker/network/model/provider/geocode/coordinate write 当时均不允许。

### 4.2 Runtime release preflight

路径：

- `tools/stage7_rewrite/reports/weekly_current_missing_geo_source_fetch_runtime_release_preflight_20260603/weekly_current_missing_geo_source_fetch_runtime_release_preflight.json`
- `reports/WEEKLY_CURRENT_MISSING_GEO_SOURCE_FETCH_RUNTIME_RELEASE_PREFLIGHT_20260603.md`

已证实：

- `decision=weekly_current_missing_geo_source_fetch_runtime_release_preflight_ready_report_only_waiting_explicit_controller_release`
- 没有创建 runtime release。

### 4.3 Controller release

路径：

- `tools/stage7_rewrite/reports/weekly_current_missing_geo_source_fetch_controller_release_20260603/weekly_current_missing_geo_source_fetch_controller_release.json`
- `reports/WEEKLY_CURRENT_MISSING_GEO_SOURCE_FETCH_CONTROLLER_RELEASE_20260603.md`

已证实：

- `decision=weekly_current_missing_geo_source_fetch_controller_release_ready_no_runtime_execution`
- `release_id=CTRL-WEEKLY-SOURCE-FETCH-L2-RUNTIME-20260603-0603-019e86a8-adb6-7953-bdfd-9bb6fa41ccd7`
- Controller release 已创建，但当时还没有 runtime execution。

### 4.4 L2 runtime result

路径：

- `tools/stage7_rewrite/reports/weekly_current_missing_geo_source_fetch_runtime_20260603_060305/weekly_current_missing_geo_source_fetch_runtime_summary.json`
- `tools/stage7_rewrite/reports/weekly_current_missing_geo_source_fetch_runtime_20260603_060305/weekly_current_missing_geo_source_fetch_runtime_results.jsonl`
- `tools/stage7_rewrite/reports/weekly_current_missing_geo_source_fetch_runtime_20260603_060305/weekly_current_missing_geo_source_fetch_runtime_blockers.jsonl`

已证实：

- `decision=weekly_current_missing_geo_source_fetch_runtime_blocked_report_local_no_coordinate_write`
- `worker_task_count=12`
- `source_url_allowlist_count=12`
- `completed_count=0`
- `blocked_count=12`
- blocker 是微信环境验证要求。

### 4.5 Result acceptance

路径：

- `tools/stage7_rewrite/reports/weekly_current_missing_geo_source_fetch_result_acceptance_packet_20260603/weekly_current_missing_geo_source_fetch_result_acceptance_packet.json`
- `reports/WEEKLY_CURRENT_MISSING_GEO_SOURCE_FETCH_RESULT_ACCEPTANCE_PACKET_20260603.md`

已证实：

- `decision=weekly_current_missing_geo_source_fetch_result_acceptance_blocked_no_coordinate_write`
- `accepted_source_evidence_count=0`
- provider/geocode、coordinate write、DB write 均未放行。

### 4.6 Blocker follow-up

路径：

- `tools/stage7_rewrite/reports/weekly_current_missing_geo_source_fetch_blocker_followup_packet_20260603/weekly_current_missing_geo_source_fetch_blocker_followup_packet.json`
- `tools/stage7_rewrite/reports/weekly_current_missing_geo_source_fetch_blocker_followup_packet_20260603/weekly_current_missing_geo_source_fetch_blocker_followup_rows.jsonl`
- `tools/stage7_rewrite/reports/weekly_current_missing_geo_source_fetch_blocker_followup_packet_20260603/weekly_current_missing_geo_manual_source_evidence_review_rows.jsonl`
- `tools/stage7_rewrite/reports/weekly_current_missing_geo_source_fetch_blocker_followup_packet_20260603/weekly_current_missing_geo_source_cache_lookup_rows.jsonl`
- `tools/stage7_rewrite/reports/weekly_current_missing_geo_source_fetch_blocker_followup_packet_20260603/weekly_current_missing_geo_authenticated_source_cache_blockers.jsonl`
- `reports/WEEKLY_CURRENT_MISSING_GEO_SOURCE_FETCH_BLOCKER_FOLLOWUP_PACKET_20260603.md`

口径：

- 12 个 WeChat environment verification blocker 被推进为无写入 follow-up。
- manual review / source-cache / authenticated-source-cache 三条 lane 都是 12。
- 没有 accepted source evidence。
- 不输出 raw source URL。

### 4.7 最新 Disposition queue

路径：

- `tools/stage7_rewrite/reports/weekly_current_missing_geo_source_fetch_disposition_queue_20260603/weekly_current_missing_geo_source_fetch_disposition_queue.json`
- `tools/stage7_rewrite/reports/weekly_current_missing_geo_source_fetch_disposition_queue_20260603/weekly_current_missing_geo_source_fetch_disposition_review_rows.jsonl`
- `tools/stage7_rewrite/reports/weekly_current_missing_geo_source_fetch_disposition_queue_20260603/weekly_current_missing_geo_source_fetch_manual_review_pending_rows.jsonl`
- `tools/stage7_rewrite/reports/weekly_current_missing_geo_source_fetch_disposition_queue_20260603/weekly_current_missing_geo_source_fetch_no_fetch_disposition_pending_rows.jsonl`
- `tools/stage7_rewrite/reports/weekly_current_missing_geo_source_fetch_disposition_queue_20260603/weekly_current_missing_geo_source_fetch_source_cache_pending_rows.jsonl`
- `reports/WEEKLY_CURRENT_MISSING_GEO_SOURCE_FETCH_DISPOSITION_QUEUE_20260603.md`

已证实：

- `decision=weekly_current_missing_geo_source_fetch_disposition_queue_ready_report_only`
- `mode=report_only_no_fetch_no_write_no_credentials`
- `disposition_row_count=12`
- `input_followup_row_count=12`
- `accepted_no_fetch_pending_count=12`
- `manual_review_pending_count=12`
- `authenticated_release_required_count=12`
- `source_cache_not_checked_count=12`
- `accepted_source_evidence_count=0`
- `coordinate_write_allowed_count=0`
- `db_write_allowed_count=0`
- `provider_or_geocode_call_allowed_count=0`
- `source_cache_lookup_allowed_now_count=0`
- `raw_url_output_count=0`
- `raw_url_private_path_secret_leak_count=0`
- `blocker_reason_counts.wechat_environment_verification_required=12`
- `recommended_lane_counts.manual_source_evidence_review=12`
- `next_required_gate=manual_source_evidence_acceptance_or_accepted_no_fetch_disposition_or_explicit_authenticated_source_cache_release`

边界字段均为未执行：

- `docker_worker_executed=false`
- `network_fetch_executed=false`
- `deepseek_or_model_calls=false`
- `provider_or_geocode_calls=false`
- `database_mutations=false`
- `registry_mutations=false`
- `coordinate_writes=false`
- `cloudbase_sync_executed=false`
- `cloudrun_deployed=false`
- `package_rebuild_executed=false`
- `upload_executed=false`
- `review_submitted=false`
- `public_release_executed=false`
- `credential_or_secret_read=false`
- `browser_profile_read=false`
- `raw_source_url_output=false`

## 5. 上下游规则

### 上游

- Atlas 地下图谱数据库是唯一上游事实源。
- Weekly/current package、source-fetch artifacts、scorecards 是 DB2/OpenClaw 消费证据，不自动成为生产许可。
- Source URL 只能通过 hash/allowlist/report-local artifact 消费；接手文档和聊天不要输出 raw source URL。

### DB2/OpenClaw 控制面

- skill/db2ctl 只保留薄控制面：解析 artifact、生成 status packet、loop/wake decision、contract/preflight/report-only verification。
- 抓取、增量更新、武器库执行最终必须进入分层 Docker/container worker/runtime。
- Codex subagent 不能作为执行集群；DB/crawler/avatar/outlink workload 必须有 worker、queue、state table、lock/lease、checkpoint、retry、log 设计。
- 当前 DB2 loop 已 fail-closed，等待 explicit controller approval 或新的 runtime report/release artifact。

### 下游

- 只有 accepted source evidence 或 accepted no-fetch disposition 才能进入 provider/geocode/coordinate acceptance。
- provider/geocode、coordinate write、DB/registry write、CloudBase sync、package rebuild、upload/review/release 都是单独 gate。
- 当前 source-fetch 链没有任何 coordinate/DB/CloudBase/package/upload/release 放行证据。

## 6. 武器库选择规则

优先从项目内 Docker worker profile/contract 出发。开源武器库只作为 worker runtime 的实现候选，不直接由 skill/Codex 裸跑成生产执行。

| 目标 | 候选工具 | 当前规则 |
| --- | --- | --- |
| 公开 profile/username breadth | `C:\code\githubstar\maigret` | 只做候选/报告，需 DB2 worker contract |
| SoundCloud | `C:\code\githubstar\SoundScrape`, `C:\code\githubstar\soundcloud-scraper` | 只处理公开页，需 allowlist/queue |
| Bandcamp | `C:\code\githubstar\bandcamp-scraper`, `C:\code\githubstar\BandcampDownloader` | 不裸跑生产下载 |
| Resident Advisor | `C:\code\githubstar\resident-advisor-scraper` | 只做证据候选 |
| 小红书 | `C:\code\githubstar\XHS-Downloader`, `C:\code\githubstar\all-in-one-rednote-xiaohongshu-scraper` | 不读账号/cookie，除非用户显式给路径和域名 |
| Bilibili | `C:\code\githubstar\BiliBiliToolPro`, `C:\code\githubstar\bilibili-api` | 公开证据优先 |
| Weibo | `C:\code\githubstar\crawl4weibo` | 公开证据优先 |
| 渲染页 fallback | `Scrapling`, `Lightpanda`, `BrowserAct`, `camofox-browser`, `chrome-devtools-mcp` | 必须受 queue/allowlist/report-only gate 控制 |
| 微信文章 source-fetch | L2 `openclaw-source-queue-cache` / `openclaw.source_queue_cache` | 当前 12 条均因微信环境验证 blocked；下一步不是重跑网络，而是 disposition/manual/source-cache gate |

## 7. 下一位 agent 应该怎么做

第一轮只读：

```powershell
git -C C:\code\.worktrees\wechathtmldownload\20260601-db2-weapons-containers status --short --branch
git -C C:\code\.worktrees\wechathtmldownload\20260601-db2-weapons-containers log -1 --oneline
python -m json.tool C:\code\.worktrees\wechathtmldownload\20260601-db2-weapons-containers\tools\stage7_rewrite\reports\db2_openclaw_loop_state_latest.json > $null
python -m json.tool C:\code\githubstar\wechathtmldownload\tools\stage7_rewrite\reports\weekly_current_missing_geo_source_fetch_disposition_queue_20260603\weekly_current_missing_geo_source_fetch_disposition_queue.json > $null
```

然后按分支：

- 如果没有新的 explicit controller gate：短状态停止。
- 如果只有 disposition/manual review packet：只做 report-only consumption，不运行网络/worker。
- 如果出现 accepted no-fetch disposition：消费为 no-fetch evidence，再等 provider/geocode/coordinate gate；不要直接写 DB。
- 如果出现 explicit authenticated/source-cache controller release：先做 preflight/contract verification，确认只限 L2、12 条 hash/allowlist、无凭据读取、无 raw URL 输出，再按主控要求执行。
- 如果出现 DB/CloudBase/upload/release 请求：要求单独 release artifact 和 acceptance packet，不从 source-fetch release 推断。

## 8. 绝对禁止

- 不读 `.env`、token、cookie、browser profile、API key、credential。
- 不输出 raw source URL。
- 不启动 Docker/worker/crawl/network/DeepSeek/API/DB/package/CloudBase/upload/release/SkillOpt，除非主线程给新的显式 controller gate。
- 不把 CloudBase AI quota、weekly frontend hotfix、rendered proof gate 当作 DB2 runtime release。
- 不清理 dirty worktree，不 reset，不 checkout，不 git clean。
- 不把 blocker 当通过处理。

## 9. 本报告生成时的核对命令

- `git status --short --branch` and `git log -1 --oneline` in `C:\code\.worktrees\wechathtmldownload\20260601-db2-weapons-containers`
- `Get-ChildItem C:\code\githubstar\wechathtmldownload\tools\stage7_rewrite\reports -Directory -Filter 'weekly_current_missing_geo_source_fetch*'`
- JSON field reads for worker contract, preflight, controller release, runtime summary, result acceptance, blocker follow-up, disposition queue.
- Loop/wake/status latest JSON field reads in DB2 worktree.
