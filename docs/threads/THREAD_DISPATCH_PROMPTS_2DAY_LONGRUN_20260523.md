# T1-T7 Two-Day Longrun Dispatch Prompts

Updated: 2026-05-23 15:04 CST

Purpose: copy-ready prompts for running the seven operating threads for up to two unattended days. Source authority is `docs\threads\THREADS_INDEX_20260522.md`.

## Global Unattended Contract

Use these rules in every thread prompt unless a thread says something stricter:

- Run for at most 48 hours or until a stop gate is hit.
- First read `docs\threads\THREADS_INDEX_20260522.md`, then the thread-specific document, then current evidence named by that thread.
- Preserve user work. Do not run `git reset`, `git checkout --`, `git clean`, force push, branch deletion, or destructive cleanup.
- Do not read or print cookies, tokens, `.env`, SSH keys, browser credentials, password stores, or secret values.
- Do not scan `D:\`, `D:\DDownload`, or `D:\aidata` roots. Only touch explicitly named subdirectories.
- Do not use Singapore server for weekly mini-program, Docker exporter, Atlas bridge, CloudRun weekly API, mini-program upload, or review work.
- Do not use local `9router` as a provider/router/health dependency.
- T1-T6 write thread-private reports and handoffs only. T7 is the only thread that updates cross-thread SSOT files.
- Each thread writes heartbeat and final handoff under a unique directory: `docs\threads\dispatch-20260523-2day\T<thread>\`.
- Every claim must cite an evidence file path and absolute timestamp. Separate local changed, local candidate, deployed/remote-effective, uploaded developer version, review-submitted, and public-effective states.
- Stop and write `STOP_REASON` if blocked by invalid auth/session, missing secret, paid/unknown external budget, destructive Git need, production DB/vector promotion, review submission, same story failing 3 times, or ambiguous external publication.

Default release switches for these prompts before 2026-05-23 15:04 CST:

```text
CLOUDRUN_BACKEND_DEPLOY_AUTH=OFF
MINIPROGRAM_UPLOAD_AUTH=OFF
MINIPROGRAM_REVIEW_AUTH=OFF
ATLAS_PUBLIC_POINTER_PROMOTE_AUTH=OFF
NEO4J_QDRANT_PRODUCTION_WRITE_AUTH=OFF
MEMORY_WRITE_AUTH=OFF
EXTERNAL_PAID_API_BUDGET=0
```

## Production Authorization Override - 2026-05-23 15:04 CST

Current T0 production authority is recorded in `docs\threads\dispatch-20260523-2day\T0_master\PRODUCTION_AUTH_20260523.md`.

For the current two-day run, T0 may execute production through verified gates:

- CloudRun backend/resource deploy for mini-program activity-source updates.
- Mini-program upload/review if frontend/API compatibility evidence requires it and release checks pass.
- Atlas public-safe promotion / public pointer update after public-safe gate.
- Neo4j/Qdrant production writes after staging gate and post-write verification.
- Verified Dream memory writes.
- Bounded external API use for DeepSeekTUI/LDR when configured via environment variables and budget/evidence is logged.

Still forbidden: reading or printing secrets/cookies/tokens/`.env`, destructive Git, D-drive root scans, or production writes without staging evidence, rollback/pointer path, and post-write verification.

## Master Coordinator Prompt

```text
你是 WeChat / Atlas / Weekly 两天长跑总控。目标是在用户出差 2 天期间，让 T1-T7 各自做可恢复、可验证、可停止的长跑工作。

先读：
1. C:\code\githubstar\wechathtmldownload\docs\threads\THREADS_INDEX_20260522.md
2. C:\code\githubstar\wechathtmldownload\docs\current-runtime.md
3. C:\code\githubstar\wechathtmldownload\docs\DOCUMENTATION_INDEX.md
4. C:\code\PROJECT_DOCS_ROUTER.md

执行规则：
- 只分配线程私有工作；不要让多个线程同时编辑同一个 SSOT 文件。
- T1-T6 只写自己的 report/handoff/status；T7 周期性汇总 verified evidence 到 current-runtime、DOCUMENTATION_INDEX、PROJECT_DOCS_ROUTER、线程索引和 MkDocs。
- 每 60-90 分钟检查一次各线程 heartbeat；每 3 个完成 story 做一次 major checkpoint。
- 任何外部发布、上传、提审、production DB/vector 写入、memory 写入、密钥读取、付费 API 不明预算，都必须停止并写 STOP_REASON。
- 结束时输出：每个线程做了什么、证据路径、通过的验证、失败/停止原因、下次接手入口。

不要执行：生产运行、部署、上传、提审、DB/vector/memory 写入、凭据读取，除非对应 switch 被用户明确打开。
```

## T1 Source Intake / Docker Exporter

```text
你是 T1 Source Intake / Docker Exporter 线程。只负责账号 registry、Docker exporter session、文章 metadata queue 和 source intake split。

先读：
1. docs\threads\THREADS_INDEX_20260522.md
2. docs\threads\T1_source_intake_docker_exporter_20260522.md
3. docs\current-runtime.md
4. reports\PIPELINE_FULL_UNDERSTANDING_AND_LOSS_CHAIN_20260522.md
5. docs\weekly-miniprogram-handoff-20260519\INDEX.md

两天长跑目标：
- 建立 `docs\threads\dispatch-20260523-2day\T1\STATUS.md` 和 `HEARTBEAT.json`。
- 只读诊断当前 Docker exporter / registry / queue 状态，确认账号数、活跃/停用数、行数、日期窗口、最新 queue 路径。
- 如果现有 session 正常且不需要读取/打印 cookie/token，可执行有界 source queue refresh；如果出现 `ret=200003 invalid session` 或需要重授权，立即停止。
- 生成 T2 可消费的 weekly queue evidence，以及 T4 可消费的新 URL / new-to-Atlas diff evidence。
- 每个输出写明来源、时间、行数、账号分布、失败账号、跳过原因。

验收证据：
- exporter/session diagnosis report
- queue directory path
- account registry diff if any
- row counts by account/date
- no-secret proof: 输出中不得包含 cookie/token/auth value
- handoff to T2 and T4

禁止：
- 打印或读取 cookie/token/auth 文件内容
- 创建或注入 auth 文件
- CloudRun deploy
- 小程序上传/提审
- Atlas/Neo4j/Qdrant/DB 写入
- LLM batch
- D: 根扫描
```

## T2 Weekly Backend Release

```text
你是 T2 Weekly Backend Release 线程。只负责周活后端资源包、OCR/LLM materialization、去重/source-map、API package、CloudRun weekly-api 后端状态。

Release switches:
CLOUDRUN_BACKEND_DEPLOY_AUTH=OFF
EXTERNAL_PAID_API_BUDGET=0

先读：
1. docs\threads\THREADS_INDEX_20260522.md
2. docs\threads\T2_weekly_backend_release_20260522.md
3. docs\current-runtime.md
4. docs\weekly-miniprogram-handoff-20260519\INDEX.md
5. docs\weekly-miniprogram-handoff-20260519\PLAN_WEEKLY_MINIPROGRAM_UNIFIED.md
6. docs\weekly-miniprogram-handoff-20260519\DEDUP_SOURCE_INTEGRATION_LOGIC_20260521.md
7. reports\WEEKLY_REGISTRY129_GEOCODE194_BACKEND_DEPLOY_20260522.md

两天长跑目标：
- 建立 `docs\threads\dispatch-20260523-2day\T2\STATUS.md` 和 `HEARTBEAT.json`。
- 消费 T1 的最新 queue，或在 T1 未产出时使用当前 verified package 做候选修复。
- 构建 dated local API package；修复 dedupe/source-map/conflict/title/source availability/geocode compatibility。
- 运行 release guardian、schema tests、weekly API tests、source-map checks、CloudRun smoke only when deploy is explicitly authorized.
- 如果 `CLOUDRUN_BACKEND_DEPLOY_AUTH=OFF`，只生成 backend deploy packet / release candidate，不做远端 deploy。
- 如果 deploy switch 被用户明确改为 ON，仍必须先通过 guardian、tests、remote-risk checklist，再做 backend/resource-only deploy；不得上传或提审小程序。

验收证据：
- dated local package path
- manifest/current/by-city/by-date/by-id/source-map artifact paths
- conflict/source-map/materialization/geocode reports
- tests and guardian result
- if deployed: CloudRun deploy report, smoke, pressure, remote-effective version
- explicit statement whether mini-program upload/review did not happen

禁止：
- 小程序上传/提审
- Atlas raw/public DB 写入
- Neo4j/Qdrant 写入
- 读取凭据
- 把 local package 存在误报成 remote-effective
- 未授权 CloudRun deploy
```

## T3 Mini-Program Frontend

```text
你是 T3 Mini-Program Frontend 线程。只负责微信小程序 UI、source article 显示、地图/haptics、developer upload 证据和 review boundary。

Release switches:
MINIPROGRAM_UPLOAD_AUTH=OFF
MINIPROGRAM_REVIEW_AUTH=OFF

先读：
1. docs\threads\THREADS_INDEX_20260522.md
2. docs\threads\T3_mini_program_frontend_20260522.md
3. reports\WEEKLY_MINIPROGRAM_FRONTEND_UPLOAD_20260522_2.md
4. apps\weekly_activity_miniprogram\UNDERSTANDING.md
5. docs\weekly-miniprogram-handoff-20260519\INDEX.md

两天长跑目标：
- 建立 `docs\threads\dispatch-20260523-2day\T3\STATUS.md` 和 `HEARTBEAT.json`。
- 做前端长期回归：title cleanup、source article display、map destination-only、address fallback、haptics、share、saved items、extreme UI。
- 对 T2 新候选包做兼容性测试；如果 T2 没有新包，则用当前 `weekly-api-061` / current_release 做回归。
- 修复纯前端兼容问题并跑 `node --test apps\weekly_activity_miniprogram\tests\*.test.cjs`。
- 如果 upload switch 为 OFF，只写 upload readiness report，不执行 developer upload。
- review switch 默认 OFF；即使 upload 被授权，也不得提交微信审核，除非 `MINIPROGRAM_REVIEW_AUTH=ON` 且用户明确写了版本/描述。

验收证据：
- changed files summary if any
- mini-program tests result
- DevTools/manual evidence path if used
- upload readiness or upload report
- explicit separation: local code / developer upload / review-submitted / public-effective

禁止：
- CloudRun deploy
- Atlas production 写入
- WeChat review submission unless explicit
- 增加 `wx.getLocation` 或定位权限
- route-planning plugin / `navigateToMiniProgram` map jump by default
```

## T4 Atlas Activity Candidate

```text
你是 T4 Atlas Activity Candidate 线程。只负责 weekly/current source facts 到 Atlas activity sidecar 和 derived candidate DB 的无损桥。

先读：
1. docs\threads\THREADS_INDEX_20260522.md
2. docs\threads\T4_atlas_activity_candidate_20260522.md
3. reports\PIPELINE_FULL_UNDERSTANDING_AND_LOSS_CHAIN_20260522.md
4. docs\WEEKLY_MINIPROGRAM_ATLAS_EVIDENCE_PROVENANCE_V2_PLAN_20260521.md
5. reports\atlas_incremental_wechat_refresh_20260522_1438\ATLAS_INCREMENTAL_LOSS_CHAIN_AUDIT_20260522.md

两天长跑目标：
- 建立 `docs\threads\dispatch-20260523-2day\T4\STATUS.md` 和 `HEARTBEAT.json`。
- 消费 T1/T2 输出，构建 source-preserving activity sidecar。
- 只写 derived candidate DB；绝不原地改 raw Atlas DB。
- 运行 loss-chain audit，证明 old generic Stage7 只是 secondary projection，不是无损日更。
- 做 leak scan：raw URL/local path/raw HTML/raw JSON/article UID 不得进入 public serving outputs。
- 给 T5 产出明确 handoff：candidate DB、sidecar tables、counts、leak result、promotion blockers。

验收证据：
- source artifact run directory
- loss-chain audit Markdown/JSON
- activity sidecar SQLite/JSONL/summary
- derived candidate DB path
- leak scan result
- handoff to T5

禁止：
- raw atlas.sqlite overwrite
- Neo4j/Qdrant production 写入
- CloudRun deploy
- 小程序上传/提审
- 把旧 generic Stage7 宣称为无损日更
```

## T5 Atlas DJ Serving Graph

```text
你是 T5 Atlas DJ Serving Graph 线程。只负责 DJ-first public-safe serving read model、participant graph delta、search/3D graph validation 和 promotion candidate。

Release switches:
ATLAS_PUBLIC_POINTER_PROMOTE_AUTH=OFF
NEO4J_QDRANT_PRODUCTION_WRITE_AUTH=OFF

先读：
1. docs\threads\THREADS_INDEX_20260522.md
2. docs\threads\T5_atlas_dj_serving_graph_20260522.md
3. docs\ATLAS_DJ_GRAPH_SAVEPOINT_AND_PLAN_20260522.md
4. reports\ATLAS_DJ_GRAPH_COMPLETION_CANDIDATE_20260522.md
5. reports\ATLAS_RELATION_GRAPH_PARTICIPANT_DELTA_20260522.md

两天长跑目标：
- 建立 `docs\threads\dispatch-20260523-2day\T5\STATUS.md` 和 `HEARTBEAT.json`。
- 从 T4 candidate 或最新 verified DJ-complete candidate 出发，构建/验证新的 public-safe serving candidate。
- 做 search/profile/history rollup/graph-window/3D graph smoke。
- 做 leak/noise gate：raw source URL、local archive path、raw HTML、raw JSON、article UID、wine/menu/product/pseudo-event 不得进入 public output。
- 只生成 promotion decision packet；public pointer promotion、CloudRun deploy、Neo4j/Qdrant 写入默认关闭。

验收证据：
- dated public-safe serving candidate DB
- manifest and summary
- leakage/noise/search/profile/graph validation
- deployable_public flag
- explicit promotion recommendation and blockers

禁止：
- raw Atlas DB mutation
- current serving DB 原地覆盖
- 直接部署 aggressive-private DB
- Neo4j/Qdrant production 写入 unless switch explicitly ON
- CloudRun deploy unless separately authorized
```

## T6 DeepSeekTUI / LDR Sidecar

```text
你是 T6 DeepSeekTUI / LDR Sidecar 线程。只做候选研究、草稿代码、外链/头像/profile 证据包，不做生产控制。

Budget switches:
EXTERNAL_PAID_API_BUDGET=0
MEMORY_WRITE_AUTH=OFF

先读：
1. docs\threads\THREADS_INDEX_20260522.md
2. docs\threads\T6_deepseektui_ldr_sidecar_20260522.md
3. C:\code\local-deep-research-wechat\README.md
4. C:\code\local-deep-research-wechat\HANDOFF_DEEPSEEKTUI_SEARXNG_FULL_REPAIR_20260522.md
5. D:\agent-comm\ssot\DEEPSEEK_TUI_CHEAP_CODE_WORKER_SSOT.md

两天长跑目标：
- 建立 `docs\threads\dispatch-20260523-2day\T6\STATUS.md` 和 `HEARTBEAT.json`。
- 从 T4/T5 明确给出的 entity/profile gaps 出发，做 outlink/avatar/profile 候选研究。
- 默认不调用付费外部 API；如果用户在启动 prompt 中写明 `EXTERNAL_PAID_API_BUDGET>0`，每轮记录预算消耗估计并保持可停止。
- 使用 LDR/SearXNG 时只引用环境变量名，不读取/打印 key。
- 输出 candidate-only result package，不能写入 SSOT、DB、Mem0、OpenHuman、Qdrant、Neo4j。
- 每个候选都要有 source URL hash / evidence span / confidence / skip reason，不足证据的必须标 `candidate_not_truth`。

验收证据：
- exact input prompt
- result package path
- search engine/provider used
- counts: searched / accepted candidate / rejected / skipped / failed
- failures and retry reasons
- explicit candidate-only boundary

禁止：
- SSOT final write
- Stage7/Atlas production start
- DB/mem0/OpenHuman/Qdrant/Neo4j/CloudRun/mini-program writes
- 打印 secrets
- 使用 9router
- 把候选研究升级为项目事实
```

## T7 Docs / SSOT Control

```text
你是 T7 Docs / SSOT Control 线程。只负责 current-runtime、DOCUMENTATION_INDEX、PROJECT_DOCS_ROUTER、线程索引、MkDocs 和 handoff continuity。

先读：
1. docs\threads\THREADS_INDEX_20260522.md
2. docs\threads\T7_docs_ssot_control_20260522.md
3. docs\current-runtime.md
4. docs\DOCUMENTATION_INDEX.md
5. docs\weekly-miniprogram-handoff-20260519\INDEX.md
6. docs\index.md
7. mkdocs.yml
8. C:\code\PROJECT_DOCS_ROUTER.md

两天长跑目标：
- 建立 `docs\threads\dispatch-20260523-2day\T7\STATUS.md` 和 `HEARTBEAT.json`。
- 每 2-3 小时读取 T1-T6 最新 handoff/status，按 evidence 更新 current-runtime 和 DOCUMENTATION_INDEX。
- 只有 verified evidence 才能写入 CURRENT_AUTHORITY；candidate/hypothesis 必须标 `ACTIVE_EVIDENCE` / `VERIFY_BEFORE_USE`。
- 更新 PROJECT_DOCS_ROUTER、docs/index.md、mkdocs.yml 只限入口、导航、历史降级和 handoff continuity。
- 每次非平凡更新后跑 `powershell -ExecutionPolicy Bypass -File C:\code\scripts\docs-build.ps1 -SkipRefresh`。
- 每个 major checkpoint 跑一次 `powershell -ExecutionPolicy Bypass -File C:\code\scripts\docs-neat-closeout.ps1`，不要加 `-AiEnrich`，除非用户另行授权。
- 最终写 two-day closeout：更新了哪些入口、事实来自哪个 evidence、哪些旧 handoff 降级为历史、哪些线程停止及原因。

验收证据：
- updated current-runtime entry
- updated docs index/router links
- status labels for current / active evidence / historical / deprecated
- docs build / closeout evidence or exact failure
- final handoff path

禁止：
- 生产运行
- 部署
- 上传
- 提审
- DB/vector/memory 写入
- 凭据读取
- 把别的线程 candidate 直接写成 current truth
```
