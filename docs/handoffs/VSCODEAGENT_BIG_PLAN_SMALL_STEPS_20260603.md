# VSCodeAgent Big Plan And Small Steps: Atlas / DB2 / Weekly Mini-Program

时间：2026-06-03 13:29 CST
工作区：`C:\code\githubstar\wechathtmldownload`
执行者：VSCodeAgent / CSCodeAgent
模式：计划就绪，单写者执行，发布冻结

## 一句话口径

Atlas 地下图谱数据库是生产源，DB2/OpenClaw、周更活动包、小程序和外链页面都是消费者；下一阶段先把 2026-06-03 小程序 hotfix 的前端海报真机/DevTools 证据补齐，再让 ReleaseGuard 消化最新接受态，同时继续 DB2 source-fetch disposition 和 DB3 348 relation approval，所有 Docker/DB/部署/发布动作必须走显式 gate。

## 总目标

- 让小程序前端以最新活动包正常工作：不再显示 2026-05-29 旧活动，能加载最新增量包，海报资源真实可见。
- 把已完成的开发版上传和数据库/后端修复纳入 ReleaseGuard 的当前口径，但不提交审核、不公版发布。
- 推进 DB2/OpenClaw 的 source-fetch blocker，使后续无额度时也能通过 DeepSeek/Docker 分层武器库更新增量包。
- 推进 DB3 的 S232D-3B8 relation/identity approval，使 Atlas 数据库能进入下一层 S232D-4 写入 gate。
- 把重复脚本下沉到 Docker worker/runtime；skill 只保留控制面、合同、gate 和调度，不塞大脚本。

## 硬边界

- 禁止读取 `.env`、token、cookie、浏览器 profile、私钥、密码库。
- 禁止提交微信审核、公版发布、CloudBase sync、CloudRun deploy、小程序 upload，除非用户新开明确 gate。
- 禁止 DB/registry/coordinate/provider/geocode/DeepSeek/model/Docker runtime 写入或执行，除非对应 story 明确解锁并有 controller release。
- 禁止把开发版上传等同正式发布；禁止把 poster proxy CLI 成功等同真机视觉成功。
- DB 写入、坐标写入、Docker runtime、部署、上传、发布必须由主线程单写者串行执行；VSCodeAgent 默认只做文档、测试、只读验证和候选 packet。

## 当前 Run State

- `phase`: `plan_ready`
- `current_story`: `VSA-00`
- `release_freeze`: `true`
- `single_writer`: `main_controller_only`
- `next_resume_cursor`: 本文件 `VSA-00`
- `poster_visual_proof`: `pending`
- `releaseguard_latest_acceptance_consumed`: `pending`
- `db2_source_fetch_disposition`: `pending`
- `db3_s232d4_write_gate`: `not_released`

## 先读入口

1. `docs/current-runtime.md`
2. `docs/handoffs/HANDOFF_VSCODEAGENT_ATLAS_DB2_MINIPROGRAM_CONTINUE_20260603.md`
3. `reports/WEEKLY_MINIPROGRAM_COMPLETE_ACCEPTANCE_20260603.md`
4. `tools/stage7_rewrite/reports/weekly_miniprogram_complete_acceptance_20260603/weekly_miniprogram_complete_acceptance_20260603.json`
5. `tools/stage7_rewrite/reports/weekly_poster_loading_acceptance_20260603/poster_proxy_cli_probe.json`
6. `tools/stage7_rewrite/reports/weekly_current_missing_geo_source_fetch_disposition_queue_20260603/weekly_current_missing_geo_source_fetch_disposition_queue.json`
7. `tools/stage7_rewrite/reports/atlas_relation_identity_s232d3b8_candidate_preflight_20260603/atlas_relation_identity_s232d3b8_candidate_preflight.json`
8. 本文件。

## 大计划

### Phase A: 接手与冻结

目标：确认当前事实、锁住危险动作、避免重复部署或重复写 DB。

- VSA-00：读取权威入口并验证 JSON 可解析。
- VSA-01：确认 no review / no public release / no new deploy / no new DB writes。

### Phase B: 前端最终证据

目标：把“海报代理资源可用”推进到“当前包真机或 DevTools 视觉可用”。

- VSA-02：修复或绕过 DevTools 自动化连接问题，不改业务逻辑。
- VSA-03：跑当前 `2026.06.03.1244` 包 poster bindload 证据。
- VSA-04：只有证据通过后，更新接受文档和 current-runtime。
- VSA-05：跑小程序/后端/Stage7 的最小回归验证。

### Phase C: ReleaseGuard 消化最新接受态

目标：让守门线程知道主线程已经完成 74 条可见活动、CloudBase、CloudRun、开发版上传和 poster proxy 证明，但仍保持 release fail-closed。

- VSA-06：创建 ReleaseGuard consumption status。
- VSA-07：更新 latest status / SSOT / 文档索引。
- VSA-08：跑 ReleaseGuard 只读验证，确认 review/release 仍 false。

### Phase D: DB2/OpenClaw source-fetch disposition

目标：不再让 12 行 source-fetch blocker 空转；先做 accepted no-fetch / manual evidence / source-cache disposition。

- VSA-09：重算 12 行是否仍属于当前电子音乐活动包 blocker。
- VSA-10：生成 manual/source-cache/no-fetch disposition packet。
- VSA-11：如仍需要认证缓存，生成 controller release 草案，但不执行。
- VSA-12：审计 L2 Docker worker contract，确认脚本下沉到容器层。

### Phase E: DB3 348 relation approval

目标：先处理 38 个 source-backed candidate，形成可审批 artifact；不要进入 S232D-4 写入。

- VSA-13：把 348 拆成 source-backed / manual / external evidence 三类。
- VSA-14：生成 S232D-3B8 approval candidate packet。
- VSA-15：做只读风险审计和 reviewer checklist。
- VSA-16：只设计 S232D-4 write gate，不执行写入。

### Phase F: 正式发布预备

目标：只有 DB2/DB3 gate 都 green 且用户明确要求时，才进入正式审核/发布。

- VSA-17：构造 full release preflight。
- VSA-18：跑 dry-run release guard。
- VSA-19：写正式发布请求 handoff，等待用户批准。

### Phase G: Docker 武器库分层

目标：长期把抓取、增量更新、DeepSeek 兜底、坐标/证据处理沉到 Docker worker；skills 只调用 dockerized entrypoint。

- VSA-20：梳理 L0-L7 worker layer map。
- VSA-21：把可重复脚本归类成 container entrypoint 候选。
- VSA-22：做 no-network/no-secret dry-run 合同测试。
- VSA-23：更新 skill/control-plane 文档，禁止把长脚本塞回 skill。

## 小步骤 Story Queue

| ID | 任务 | 输入 | 允许动作 | 产出 | 验收 | 停止条件 |
| --- | --- | --- | --- | --- | --- | --- |
| VSA-00 | 权威入口接手 | `docs/current-runtime.md`、VSCodeAgent handoff、本计划 | `git status`、JSON parse、只读 `rg` | `reports/vscodeagent_takeover_probe_20260603.md` 或等价记录 | 读序文件存在；3 个关键 JSON parse ok；当前 branch 和 dirty state 记录清楚 | 任一权威文件缺失或 JSON 损坏 |
| VSA-01 | 发布冻结确认 | acceptance JSON、upload log、ReleaseGuard latest | 只读检查 | freeze note | `wechat_review_submitted=false`；`wechat_public_release_executed=false`；没有新 deploy/upload 证据 | 发现已审核/已发布/新上传未记录 |
| VSA-02 | DevTools 阻塞定位 | `apps/weekly_activity_miniprogram/tests/devtools-current-package-rendered.cjs`、失败 artifacts | 改测试 harness 或启动参数；不改生产逻辑 | DevTools blocker report 或修复 patch | 能稳定 launch/connect，或明确记录工具阻塞和下一诊断命令 | 需要读取 profile/cookie 或启动外部账号态 |
| VSA-03 | 当前包海报视觉证据 | dev upload `2026.06.03.1244`、poster proxy probe | DevTools/真机只读渲染验证 | `tools/stage7_rewrite/reports/weekly_poster_loading_acceptance_20260603/current_package_visual_proof_*.json` | `posterImageLoadCount >= 1` 且 `posterImageErrorCount == 0`，或截图/日志证明海报可见 | DevTools/真机无法运行，写 blocker 不伪造通过 |
| VSA-04 | 接受文档升级 | VSA-03 产物、complete acceptance doc | 文档更新 | updated acceptance/current-runtime/SSOT | 文档从 backend proxy proven 升级为 visual/bindload proven 时必须引用 VSA-03 文件 | VSA-03 未通过 |
| VSA-05 | 小程序回归验证 | 小程序 tests、weekly-api tests、Stage7 targeted tests | CLI 测试 | test summary | 关键测试通过，失败则列出具体失败文件和命令 | 同一失败修复 3 次仍无进展 |
| VSA-06 | ReleaseGuard 消费最新接受态 | complete acceptance JSON、poster proof | 生成 consumption status；不 release | `*_complete_acceptance_20260603_consumption_status.json` | 记录 74 visible、0 old rows、0 missing geo、review/release false | 发现接受态与 public probe 冲突 |
| VSA-07 | 更新 ReleaseGuard 口径 | VSA-06 产物、SSOT、index | 文档/JSON 指针更新 | docs/current-runtime、SSOT、DOCUMENTATION_INDEX patch | 最新接受态可从索引第一组找到；旧 78/19 blocker 不覆盖 74/0 hotfix 状态 | 需要生产动作才能验证 |
| VSA-08 | 守门验证 | ReleaseGuard scripts/reports | 只读 guard/test | guard verification report | release_ready 仍 false；review/release allowed 仍 false；latest dev-upload accepted | guard 输出 release_ready true 但 DB3 未过 |
| VSA-09 | DB2 12 行当前性复核 | source-fetch disposition queue、current package | 只读 join/filter | `db2_source_fetch_currentness_review_20260603.json` | 标出仍 current、已被移除、非电子音乐、需人工证据的行数 | 需要 raw URL 或 credential |
| VSA-10 | DB2 disposition packet | VSA-09、manual evidence notes、source-cache metadata | 生成 report-only packet | accepted no-fetch/manual/source-cache disposition artifact | accepted_source_evidence 只来自可审计证据；raw URL leak 0 | 证据不足则保持 pending |
| VSA-11 | 认证缓存 release 草案 | VSA-10 unresolved rows、worker contract | 写 controller release draft；不执行 | authenticated/source-cache controller release draft | all execution flags false；列明 release 前置条件 | 用户未批准 runtime |
| VSA-12 | L2 Docker worker contract 审计 | db2ctl、Docker profiles plan、worker contract | 只读审计/小 patch 文档 | Docker worker contract audit | skill=control plane；worker=container entrypoint；checkpoint/retry/log/kill-switch 明确 | 需要启动 Docker 或读 secret |
| VSA-13 | DB3 348 分类复核 | S232D-3B8 preflight | 只读分类 | `db3_s232d3b8_classification_review_20260603.json` | 38 source-backed、93 manual、217 external evidence 数字解释清楚 | preflight 与当前数据不一致 |
| VSA-14 | DB3 approval candidate | VSA-13、source-backed evidence | 生成 candidate packet | S232D-3B8 approval candidate artifact | approved_for_s232d4_count 仍 0；只是候选 | 证据不能支持同一身份/关系 |
| VSA-15 | DB3 reviewer checklist | VSA-14 | 只读审计 | reviewer checklist | 每个候选有 accept/reject/defer 条件；merge/write allowed 0 | 需要人工判断但无证据 |
| VSA-16 | S232D-4 write gate 设计 | VSA-15 | 设计文档；不写 DB | S232D-4 gate design | backup、lock、transaction、readback、rollback、no-empty-overwrite 齐全 | 用户未批准写入 |
| VSA-17 | 全链路 release preflight | VSA-04、VSA-08、VSA-10、VSA-16 | 只读 preflight | full release preflight packet | 所有 gate 明确 pass/block；无模糊 release_ready | 任一 gate blocked |
| VSA-18 | dry-run ReleaseGuard | VSA-17 | dry-run guard | dry-run report | public release still requires explicit user approval | guard 需要真实上传/发布 |
| VSA-19 | 正式发布请求包 | VSA-18 | handoff only | release approval request | 列明将执行的 upload/review/release 命令和风险 | 用户未明确批准 |
| VSA-20 | Docker layer map | OpenClaw plans、db2ctl、worker contracts | 文档/架构图 | `docs/handoffs/openclaw_docker_layer_map_20260603.md` | L0-L7 边界清楚；skill 不包含大脚本 | 需要运行 Docker |
| VSA-21 | Entrypoint 候选归类 | scripts、worker contract tests | 只读/文档 | entrypoint candidate list | 每个脚本归属 worker、输入、输出、日志、retry | 脚本依赖 secret/profile |
| VSA-22 | 合同 dry-run 测试 | worker contract tests | no-network/no-secret tests | contract test report | 不联网、不读密钥、不写 DB；测试可重复 | 需要真实 source/auth |
| VSA-23 | Skill 控制面更新 | skills/db2ctl docs | 文档 patch | updated control-plane docs | skill 只启动/检查 container worker；不内嵌长脚本 | 未完成 VSA-20/21/22 |

## Checkpoints

- Checkpoint 1 after VSA-00..VSA-03：前端证据路线清楚，无法证明就留下 blocker，不继续 release 文档。
- Checkpoint 2 after VSA-04..VSA-08：ReleaseGuard 已消化最新小程序接受态，但 release 仍冻结。
- Checkpoint 3 after VSA-09..VSA-12：DB2 source-fetch blocker 有 disposition 或明确 authenticated/source-cache release 草案。
- Checkpoint 4 after VSA-13..VSA-16：DB3 348 有 approval candidate，不写 S232D-4。
- Checkpoint 5 after VSA-17..VSA-19：只有用户批准才进入正式发布。
- Checkpoint 6 after VSA-20..VSA-23：Docker 武器库分层合同完成，skills 继续保持薄控制面。

## VSCodeAgent 首轮命令

从 `C:\code\githubstar\wechathtmldownload` 执行：

```powershell
git branch --show-current
git status --short --branch -- docs/current-runtime.md docs/DOCUMENTATION_INDEX.md tools/stage7_rewrite/SSOT.md reports/WEEKLY_MINIPROGRAM_COMPLETE_ACCEPTANCE_20260603.md
node -e "JSON.parse(require('fs').readFileSync('tools/stage7_rewrite/reports/weekly_miniprogram_complete_acceptance_20260603/weekly_miniprogram_complete_acceptance_20260603.json','utf8')); console.log('acceptance ok')"
node -e "JSON.parse(require('fs').readFileSync('tools/stage7_rewrite/reports/weekly_current_missing_geo_source_fetch_disposition_queue_20260603/weekly_current_missing_geo_source_fetch_disposition_queue.json','utf8')); console.log('db2 queue ok')"
node -e "JSON.parse(require('fs').readFileSync('tools/stage7_rewrite/reports/atlas_relation_identity_s232d3b8_candidate_preflight_20260603/atlas_relation_identity_s232d3b8_candidate_preflight.json','utf8')); console.log('db3 preflight ok')"
node -e "JSON.parse(require('fs').readFileSync('tools/stage7_rewrite/reports/weekly_poster_loading_acceptance_20260603/poster_proxy_cli_probe.json','utf8')); console.log('poster proxy ok')"
```

## 每个 Story 的收尾格式

每完成一个 story，VSCodeAgent 必须写一段简短状态到对应 report 或 handoff：

```text
story_id:
status: passed | blocked | failed
changed_files:
verification:
remaining_risk:
next_story:
unsafe_actions_still_forbidden:
```

## Assumption Ledger

- 用户说的 `cscodeagent` 按 VSCodeAgent / 接手开发 agent 处理。
- 当前计划只授权文档、只读验证、测试 harness 修复和 report-only packet；不授权任何生产写入。
- “以前端测试正常工作为最终目的”在本计划中落为 VSA-02..VSA-05，且必须有当前包视觉或 bindload 证据。
- Atlas 是上游产品源，小程序和外链是消费者；因此正式发布必须受 DB2/DB3 gate 约束，但开发版 hotfix 证据可以独立记录。

## Stop Gates

- 需要用户批准：正式 upload、微信审核、公版发布、CloudBase sync、CloudRun deploy、DB writes、coordinate writes、Docker runtime、DeepSeek/model/provider/geocode/authenticated source-cache。
- 需要停止并写 blocker：DevTools/真机无法验证海报；ReleaseGuard 状态与当前接受态冲突；DB2 证据不足；DB3 identity/relationship 证据不足；任何检查需要 secret/cookie/profile。
- 需要主线程接管：生产写入、部署、发布、跨线程目标更新、长跑 automation 更新。
