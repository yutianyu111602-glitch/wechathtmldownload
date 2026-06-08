# OpenClaw / Docker 武器库接手报告

生成时间：2026-06-03  
主仓：`C:\code\githubstar\wechathtmldownload`  
DB2/OpenClaw worktree：`C:\code\.worktrees\wechathtmldownload\20260601-db2-weapons-containers`  
当前主线：Atlas / HUAIDJ 方案 A 的下游抓取、增量、预处理、DB2 外链和 weekly package 控制面。  

## WSL2 目录对照

默认 WSL distro：`Ubuntu`。

| 用途 | Windows 路径 | WSL 路径 | Explorer UNC |
| --- | --- | --- | --- |
| 主仓 | `C:\code\githubstar\wechathtmldownload` | `/mnt/c/code/githubstar/wechathtmldownload` | `\\wsl.localhost\Ubuntu\mnt\c\code\githubstar\wechathtmldownload` |
| DB2/OpenClaw worktree | `C:\code\.worktrees\wechathtmldownload\20260601-db2-weapons-containers` | `/mnt/c/code/.worktrees/wechathtmldownload/20260601-db2-weapons-containers` | `\\wsl.localhost\Ubuntu\mnt\c\code\.worktrees\wechathtmldownload\20260601-db2-weapons-containers` |
| 本接手文档 | `C:\code\githubstar\wechathtmldownload\docs\handoffs\HANDOFF_OPENCLAW_DOCKER_WEAPONS_20260603.md` | `/mnt/c/code/githubstar/wechathtmldownload/docs/handoffs/HANDOFF_OPENCLAW_DOCKER_WEAPONS_20260603.md` | `\\wsl.localhost\Ubuntu\mnt\c\code\githubstar\wechathtmldownload\docs\handoffs\HANDOFF_OPENCLAW_DOCKER_WEAPONS_20260603.md` |
| OpenClaw L1-L6 runtime report dir | `C:\code\githubstar\wechathtmldownload\tools\stage7_rewrite\reports\openclaw_l1_l6_container_dry_run_runtime_20260602_220147` | `/mnt/c/code/githubstar/wechathtmldownload/tools/stage7_rewrite/reports/openclaw_l1_l6_container_dry_run_runtime_20260602_220147` | `\\wsl.localhost\Ubuntu\mnt\c\code\githubstar\wechathtmldownload\tools\stage7_rewrite\reports\openclaw_l1_l6_container_dry_run_runtime_20260602_220147` |
| OpenClaw latest weekly report dir | `C:\code\githubstar\wechathtmldownload\tools\stage7_rewrite\reports\openclaw_weekly_daily_20260603_014551` | `/mnt/c/code/githubstar/wechathtmldownload/tools/stage7_rewrite/reports/openclaw_weekly_daily_20260603_014551` | `\\wsl.localhost\Ubuntu\mnt\c\code\githubstar\wechathtmldownload\tools\stage7_rewrite\reports\openclaw_weekly_daily_20260603_014551` |
| Source-fetch L2 runtime report dir | `C:\code\githubstar\wechathtmldownload\tools\stage7_rewrite\reports\weekly_current_missing_geo_source_fetch_runtime_20260603_060305` | `/mnt/c/code/githubstar/wechathtmldownload/tools/stage7_rewrite/reports/weekly_current_missing_geo_source_fetch_runtime_20260603_060305` | `\\wsl.localhost\Ubuntu\mnt\c\code\githubstar\wechathtmldownload\tools\stage7_rewrite\reports\weekly_current_missing_geo_source_fetch_runtime_20260603_060305` |
| OpenClaw / iMessage 草稿/mailroom，历史路径，使用前需确认 | `D:\agent-comm\drafts` | `/mnt/d/agent-comm/drafts` | 不建议从 Explorer 全盘扫 D，只按此目录精确打开 |

## 本线程是干什么的

这条 Codex 线程只负责 **建立可接手文档和交接边界**。它不是 OpenClaw runtime 执行线程、不是 DB2 writer、不是 DB3 写库线程、不是 ReleaseGuard、小程序上传、CloudBase 发布或 DB2 投影线程。

本线程已经做的事：

- 读取当前主仓与 controller wake-state，确认 OpenClaw L1-L6 dry-run、weekly source-fetch、DB3 relation blocker、release guard 的边界。
- 把 OpenClaw / Docker 武器库后续 agent 的接手入口、分层武器库、输入文件、禁止动作、执行 release 条件和验证口径写成本文档。
- 把 WSL2 DeepSeek TUI 后续 agent 的接手入口另写成 `docs/handoffs/HANDOFF_DEEPSEEK_TUI_DB3_RELATION_20260603.md`。
- 只写文档，不写 DB，不启动 Docker，不联网抓取，不读凭据，不发布。

后续 agent 看到本文档后，应把本线程当作“交接说明生成线程”，而不是继续在本线程里执行 OpenClaw runtime、DB2 writer、DB3 写门或生产发布。

## 给接手 Agent 的一句话

你的角色是 **OpenClaw / Docker worker runtime 管线 agent**：把抓取、增量更新、OCR、DeepSeek 提取、地图验证、package merge 等重活放进 Docker/container worker/runtime；OpenClaw/skill/db2ctl 只当薄控制面。当前不能解锁 DB3，不能发布小程序，不能直接写 DB2/DB3。

## 当前权威状态

OpenClaw L1-L6 容器 dry-run runtime 已经跑通，但只是 report-local 证明：

- 权威报告：`C:\code\githubstar\wechathtmldownload\tools\stage7_rewrite\reports\openclaw_l1_l6_container_dry_run_runtime_20260602_220147\openclaw_l1_l6_container_dry_run_runtime_summary.json`
- `decision=openclaw_l1_l6_container_dry_run_runtime_passed_report_local_no_execution`
- `l1_l6_complete=true`
- `docker_started_for_runtime_dry_run=true`
- `worker_started_for_runtime_dry_run=true`
- `network_fetch_executed=false`
- `deepseek_call_executed=false`
- `db_write_executed=false`
- `db2_projection_executed=false`
- `package_rebuild_executed=false`
- `cloudbase_sync_executed=false`
- `miniprogram_upload_executed=false`
- `public_release_executed=false`
- `raw_url_private_path_secret_leak_count=0`

这说明容器分层框架可以跑 report-local dry-run，不等于可以开始真实抓取、投影、发布。

## L1-L7 分层武器库

当前合同里的层：

| 层 | Docker profile | service | 作用 |
|---|---|---|---|
| L1 | `openclaw-source-exporter` | `openclaw-source-exporter` | 源导出 / source exporter |
| L2 | `openclaw-source-queue-cache` | `openclaw-source-queue-cache` | source queue / cache / bounded fetch |
| L3 | `openclaw-ocr` | `openclaw-ocr-worker` | OCR / poster / lineup 预处理 |
| L4 | `openclaw-llm-extraction` | `openclaw-llm-extract-worker` | DeepSeek 结构化提取 |
| L5 | `openclaw-map-verify` | `openclaw-map-verify-worker` | 地址/地图/坐标验证 |
| L6 | `openclaw-package-merge` | `openclaw-package-merge-worker` | 增量包 merge |
| L7 | deploy/upload | 不在 L1-L6 release 内 | CloudBase / 小程序上传 / review / release |

原则：

- skill/OpenClaw/db2ctl = 薄控制面。
- Docker/container worker/runtime = 执行面。
- DB2 writer = 单写门。
- 外链/坐标/source evidence = JSONL queue + cache + lease + checkpoint + retry + report-local。

## 当前 weekly / OpenClaw 相关输入

优先读这些：

1. `C:\code\githubstar\wechathtmldownload\tools\stage7_rewrite\reports\openclaw_l1_l6_container_dry_run_runtime_20260602_220147\openclaw_l1_l6_container_dry_run_runtime_summary.json`
2. `C:\code\githubstar\wechathtmldownload\tools\stage7_rewrite\reports\openclaw_docker_profiles_contract_20260602`
3. `C:\code\githubstar\wechathtmldownload\tools\stage7_rewrite\reports\openclaw_no_quota_deepseek_incremental_preflight_20260602`
4. `C:\code\githubstar\wechathtmldownload\tools\stage7_rewrite\reports\openclaw_l1_l6_container_dry_run_controller_release_20260602`
5. `C:\code\githubstar\wechathtmldownload\tools\stage7_rewrite\reports\openclaw_weekly_daily_20260603_014551`
6. `C:\code\githubstar\wechathtmldownload\tools\stage7_rewrite\reports\weekly_deploy_upload_next_gate_20260603\weekly_deploy_upload_next_gate_20260603.json`

坐标 source-fetch L2 也走 OpenClaw worker，但属于 coordinate lane，不是 DB3：

- `C:\code\githubstar\wechathtmldownload\tools\stage7_rewrite\reports\weekly_current_missing_geo_source_fetch_controller_release_20260603\weekly_current_missing_geo_source_fetch_controller_release.json`
- `C:\code\githubstar\wechathtmldownload\tools\stage7_rewrite\reports\weekly_current_missing_geo_source_fetch_runtime_20260603_060305\weekly_current_missing_geo_source_fetch_runtime_summary.json`
- 结果：12 条 source fetch 全部因 `wechat_environment_verification_required` blocked，`accepted_source_evidence_count=0`。

## 当前 release / deploy 关系

小程序 local rendered gate 已绿，但 formal release 仍 fail-closed。当前剩余主 blocker：

1. 坐标 freshness：`current_items_missing_geo=78`，其中 59 条 registry-backed coordinate runtime 已 readback pass，但 12 条 source-fetch / 7 条 address-provider 仍有后续门。
2. DB3 relation integrity：`db3_same_normalized_name_multi_id=348`，S232D-3B7 仍 `approved_for_s232d4_count=0`。

OpenClaw agent 不要把 L1-L6 dry-run 误判成 release 绿灯。

## 能做什么

允许的安全动作：

- 只读读取 report-local artifacts。
- 检查 Docker profile contract 与 L1-L6 dry-run report 是否一致。
- 设计 queue/lease/checkpoint/retry/log。
- 设计 source cache 与 file lock 策略。
- 生成 report-only controller packet。
- 在收到显式 controller release 后，按 release 指定范围跑 bounded Docker worker。
- 所有输出进入 report-local evidence 目录。

## 不能做什么

没有显式 controller release 时禁止：

- 不启动 Docker/worker 做真实抓取。
- 不联网抓取、不访问 provider、不用地图 API。
- 不读 cookie/token/API key/`.env`/浏览器 profile。
- 不写 DB1/DB2/DB3，不写 SQL spool。
- 不做 DB2 projection，不 promotion candidate。
- 不 package rebuild。
- 不 CloudRun deploy，不 CloudBase sync。
- 不小程序 upload/review/release。
- 不把 DB2/OpenClaw 证据当成 DB3 S232D-4 写门。

## 如收到真实执行 release，必须这样跑

先确认 release id、允许范围、allowlist、输出目录，然后执行：

1. Preflight
   - Docker profile 存在。
   - 输入只读挂载。
   - 输出 report-local 可写。
   - 不挂 production DB、browser profile、credential 目录。
   - no raw URL/private path/secret leak。

2. Runtime
   - 只跑 release 指定层，例如 L2 source fetch 或 L1-L6 dry-run。
   - 只处理 release 指定 allowlist。
   - 网络只在 release 明确允许时打开。
   - 每条 task 写 checkpoint。
   - 失败要落 blocked row，不要扩大范围。

3. Post-run
   - 写 summary JSON。
   - 写 results JSONL。
   - 写 blockers JSONL。
   - 写 scorecard。
   - 记录 all DB/projection/release flags false，除非 release 明确释放。
   - 检查无残留容器。

## 当前重点后续

OpenClaw 下一步不是全链路发布，而是按主线程 gate 串行：

1. 坐标 lane：
   - 12 条 source-fetch blocked，需要 source-cache/manual/authenticated source-cache 后续决策。
   - 7 条 address-provider 还要 provider/address acceptance。

2. DB3 lane：
   - 348 relation groups 需要 source-backed disposition/merge candidates。
   - OpenClaw 不能直接解锁 S232D-4。

3. Weekly package / 小程序：
   - 只有 deploy-upload preflight required blockers 归零后，才考虑 upload/review/release。

## iMessage / OpenClaw 控制面注意

历史记忆里 OpenClaw 有 Mac 侧 iMessage bot、控制 UI、电话号/邮箱转发一类能力；这些是辅助控制面，不是数据写门。使用前必须验证当前服务状态，不要依赖旧端口或旧登录态。二维码、cookie、API key、browser profile 不得写入报告。

## 最小接手步骤

接手后先做这个小切片：

1. 读 `openclaw_l1_l6_container_dry_run_runtime_summary.json`。
2. 读 `weekly_deploy_upload_next_gate_20260603.json`。
3. 确认 OpenClaw L1-L6 仍只是 `report_local_no_execution`。
4. 确认是否出现新的 explicit controller release。
5. 没有 release 就只输出状态，不启动 Docker。

## 验证口径

每轮结束必须报告：

- `controller_release_present`
- `docker_started`
- `worker_started`
- `network_fetch_executed`
- `deepseek_call_executed`
- `db_write_executed`
- `db2_projection_executed`
- `package_rebuild_executed`
- `cloudbase_sync_executed`
- `miniprogram_upload_executed`
- `public_release_executed`
- `raw_url_private_path_secret_leak_count`
- `remaining_blockers`
