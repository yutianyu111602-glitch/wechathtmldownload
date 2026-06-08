# Atlas / HUAIDJ S1-S115 接手文档

Updated: 2026-06-01 13:55 CST

## Main Problem

当前主线不是“已完成部署”，而是把 Atlas / HUAIDJ 小程序、CloudRun、OpenClaw、DB1/DB2/DB3、坐标、关系图谱、mixtape/采访等先后开发的模块统一成可审计、可恢复、不会错误写入生产数据的长跑系统。

## Scope

- Repo: `C:\code\githubstar\wechathtmldownload`
- Branch: `codex/atlas-db-unification-20260531`
- Current story: `S115`
- Current authority:
  - `docs/longrun/atlas-route-external-db-20260531/04-prd.json`
  - `docs/longrun/atlas-route-external-db-20260531/manifest.md`
  - `docs/current-runtime.md`
  - `docs/DOCUMENTATION_INDEX.md`
- Latest scorecard: `reports/WEEKLY_ATLAS_RELATION_IDENTITY_WRITE_GATE_STARTER_S115_20260601.md`
- Latest S115 packet: `tools/stage7_rewrite/reports/atlas_relation_identity_write_gate_starter_s115_20260601/atlas_relation_identity_write_gate_starter_packet.json`

In scope:

- Report-only blocker hardening.
- DB1/DB2/DB3 字段、ID、关系、空字段覆盖、source_ref、mixtape/social/bio/avatar 字段守门。
- DJ-DJ、DJ-event、DJ-venue、venue-DJ 关系读回和写门前审计。
- 小程序静态测试、按钮/事件覆盖、外链版权边界。
- OpenClaw/weekly 管线冻结、调度器审计和不运行前提下的修复计划。

Out of scope until blockers clear:

- 不运行 OpenClaw/weekly 自动管线。
- 不调用腾讯/高德/地图 provider/geocode。
- 不启动微信 DevTools。
- 不 deploy/upload/submit review。
- 不写 DB/graph/vector/public pointer。
- 不写坐标。
- 不读 secrets，不重启服务，不扫 `D:\` 大根，不调用 LLM/API。

## Current Reality

### Confirmed

- `S115` 已生成 relation identity write-gate starter packet，决策为 `atlas_relation_identity_write_gate_starter_blocked_report_only`。
- 当前活跃目标仍未完成：`weekly_goal_completion_audit_not_complete`，completed `7`，incomplete `3`。
- 三个顶层 blocker 仍在：
  - `deploy_upload_local_preflight`
  - `address_coordinate_repair`
  - `rendered_devtools_miniapp_coverage`
- 坐标 blocker 仍在：`S109` 显示 safe-to-claim latest `false`，current missing geo `1`，stale registry rows `59`，Rust Club provider accepted `0`。
- 关系/身份 blocker 仍在：`S111` 显示 relation blockers `2045`，approved write-gate rows `0`，write-gate candidates `0`。
- DevTools blocker 仍在：`S101/S100` 显示 current pass artifact `0`，环境 dirty，busy target port `9430`。
- `S114` 已证明历史用户命令总账对当前 S109/S111/S112/S113 blocker 已过期，stale/missing-current findings `15`。
- PRD 当前故事编号缺 `S41`；当前文件中从 `S40` 直接到 `S42`，不要补造不存在的 S41。

### Hypotheses

- 最短可推进路径不是直接部署，而是先把 `S115` starter rows 做成可人工/证据驱动的 disposition 包，逐步产生 approved write-gate candidates。
- Rust Club 坐标问题不是“缺 key”单点问题，而是当前证据不足以达到用户要求的打车级准确性。
- DevTools 渲染覆盖问题更像本机 DevTools/automator 协议与 dirty environment 问题，不应和小程序静态测试混为一谈。

### Unverified

- 尚未确认任何 S115 starter row 可以安全合并或写 DB。
- 尚未确认 Rust Club 最新坐标可写。
- 尚未确认 DevTools rendered coverage 已恢复。
- 尚未确认最终 deploy/upload/review 可执行。

## S1-S115 做了什么

### S1-S10: 接手、边界、合同和不重复构建

- `S1`: 建立 route/external/db 只读 inventory，先看清模块和数据面。
- `S2`: 定义 canonical field / DB contract，确认 DB1/DB2/DB3 的边界。
- `S3`: 建立地址/坐标 provider cross-check queue；结果为 blocked_with_evidence。
- `S4`: 增加移动端 Atlas mixtape 和 external outlink UX。
- `S5`: 在有 runtime delta 时执行生产 deploy/upload 路径。
- `S6`: 刷新 SSOT 和 handoff。
- `S7`: 减少重复 rebuild，刷新 code graph。
- `S8`: 做 deploy/upload boundary audit。
- `S9`: 更新 active OpenClaw skill 边界。
- `S10`: 固化 DB unification boundary 和 deploy context no-op。

### S11-S20: DJ Interview、用户命令、腾讯/高德坐标 blocker

- `S11`: 部署 DJ Interview backend，并上传小程序 developer version。
- `S12`: 回忆用户命令并加固腾讯 geocode credential attempts；结果仍 blocked。
- `S13`: 把 interview mixtape/external links 接进 canonical private fields。
- `S14`: 跑小程序前端 CLI 逻辑测试，但 DevTools rendered 覆盖仍未完成。
- `S15`: 深化 DevTools automator 和 Rust Club geo source blocker evidence。
- `S16`: 按官方文档审计 Tencent geocode signature code，确认配置/鉴权 blocker。
- `S17`: 确认当前 WeChat DevTools CLI protocol mismatch。
- `S18`: 增加外部音乐/mixtape direct-media guard，避免版权风险。
- `S19`: 守住 source URL map package boundary，历史文章跳转不把全量 map 打进小程序包。
- `S20`: 用当前 Tencent/Amap provider state 复核 Rust Club 坐标，仍 blocked。

### S21-S30: 小程序体验、采访后台、关系守卫、预检扩展

- `S21`: 首页加入本周/本月预览控制。
- `S22`: 增加 DJ Interview redacted review queue。
- `S23`: 增加本地 redacted DJ Interview review packet builder。
- `S24`: 增加本地 redacted DJ Interview review workbench。
- `S25`: 增加只读 Atlas relation field integrity guard。
- `S26`: 把 relation guard 接入 deploy/upload local preflight。
- `S27`: 增加 DJ Interview intake template/importer。
- `S28`: 小程序增加 mixtape / Instagram original-link action。
- `S29`: 增加 WXML event-handler coverage guard。
- `S30`: deploy/upload preflight 扩展到所有小程序静态测试。

### S31-S40: 用户命令审计、目标审计、DevTools/Rust 坐标守门

- `S31`: 用户命令总账对齐到 S30。
- `S32`: 增加 user-command ledger evidence audit。
- `S33`: 增加 requirement-level active goal completion audit。
- `S34`: 增加 rendered DevTools coverage audit，修复 stale CLI hint。
- `S35`: goal completion audit 增加 latest evidence resolver。
- `S36`: rendered DevTools coverage audit 变成 artifact-aware。
- `S37`: 增加 Rust Club geo evidence write gate。
- `S38`: 审计 Rust Club local image / QR evidence。
- `S39`: 记录 bad-DJ coordinate MVP agent plan 和 Tencent quota probe。
- `S40`: 增加非 provider 的全量坐标质量审计。

### S42-S48: 打车级坐标、OpenClaw 冻结、字段/空覆盖

- `S42`: 强制 taxi-grade map destination gate。
- `S45`: 捕获 Rust Club 用户提供地址候选，但不提升为坐标写入。
- `S46`: 冻结 OpenClaw 和 weekly 自动管线，直到修复并验证。
- `S47`: 审计 DB 字段统一、非同名实体去重、空字段覆盖 guard。
- `S48`: 生成 empty-overwrite review packet，不写 DB。

### S49-S61: 目标审计硬化、DevTools 封锁、坐标和身份进入 deploy gate

- `S49`: S48 后刷新 active-goal completion audit。
- `S50`: 移除 rendered scripts 的固定 DevTools WebSocket 默认值。
- `S51`: 生成不启动 DevTools 的 rendered run preflight。
- `S52`: 增加 rendered DevTools safe single-attempt wrapper。
- `S53`: 执行一次 bounded rendered attempt 并审计失败。
- `S54`: 增加 DevTools rendered port guard 和 avoid-busy-port attempt。
- `S55`: 增加只读 DevTools dirty-state audit。
- `S56`: dirty environment 时阻止 rendered single-attempt execution。
- `S57`: preflight 变成 environment-aware。
- `S58`: blocked rendered preflight 默认返回非零。
- `S59`: coordinate freshness/latest-claim 未通过时默认返回非零。
- `S60`: 把 coordinate freshness latest-claim 接入 deploy/upload preflight。
- `S61`: 增加 DB3 DJ identity projection 和 split-entity guard。

### S63-S72: OpenClaw auth、DB3 identity 包、goal audit 引证链

- `S63`: 检查 OpenClaw daily pipeline Phase 1 auth failure，并加 auth report guard。
- `S64`: 生成 report-only DB3 DJ identity canonical merge packet。
- `S65`: 生成 report-only DB3 DJ identity write gate。
- `S66`: 生成 report-only DB3 DJ identity SQL dry-run packet。
- `S67`: 用当前环境 blocker 刷新 DevTools rendered coverage。
- `S68`: goal completion audit 引用最新 rendered DevTools blocker evidence。
- `S69`: 禁用重复 legacy OpenClaw daily cron scheduler。
- `S70`: goal completion audit 引用 coordinate freshness blocker evidence。
- `S71`: goal completion audit 引用 deploy/upload preflight failed check evidence。
- `S72`: goal completion audit 引用 relation integrity finding details。

### S73-S89: DB3 DJ identity review 全覆盖，但仍不写

- `S73`: 生成 report-only DB3 DJ identity review workbench，覆盖 `2012` review rows。
- `S74`: goal completion audit 引用 identity review workbench。
- `S75`: 生成 high-risk DB3 DJ identity review packet。
- `S76`: 生成 high-risk disposition template。
- `S77`: 验证 high-risk disposition，approved/write candidates 仍为 `0`。
- `S78`: goal completion audit 引用 disposition validation。
- `S79`: 为 high-risk pending identity rows 生成 stable-id review queue。
- `S80`: goal completion audit 引用 stable review queue。
- `S81`: 拆出 source-ref collection queue。
- `S82`: goal completion audit 引用 source-ref queue。
- `S83`: 生成 lineup confirmation queue。
- `S84`: 验证 lineup confirmation rows。
- `S85`: 验证 source-ref collection rows。
- `S86`: 合并 source-ref 和 lineup tasks 到 next-action packet。
- `S87`: 生成 non-high DB3 DJ identity review batches。
- `S88`: 验证 non-high review batches。
- `S89`: 证明 high/non-high identity review coverage 完整，gap `0`；但仍不授权写 DB。

### S90-S99: 三大 blocker 拆包和闭环矩阵

- `S90`: 生成 coordinate repair next-action packet。
- `S91`: 把剩余 goal blockers 合并为 no-write next-action packet。
- `S92`: 把 rendered DevTools blocker 拆为 no-run next-action tasks。
- `S93`: 把 deploy/upload preflight blocker 拆为 report-only gates。
- `S94`: 在 S46 冻结边界下冻结 residual OpenClaw stable deploy crontab lane。
- `S95`: 增加 repeatable OpenClaw scheduler freeze audit。
- `S96`: 增加 relation identity write blocker audit。
- `S97`: 增加 coordinate write blocker audit。
- `S98`: 增加 DevTools rendered blocker audit。
- `S99`: 增加 remaining blocker closure matrix。

### S100-S115: 当前化、SSOT 指针、总账对账、关系写门 starter

- `S100`: 刷新 DevTools environment reset blocker readback。
- `S101`: 刷新 DevTools protocol adapter diagnosis evidence。
- `S102`: 增加 DB3 relation identity write-gate exit matrix。
- `S103`: 增加 SSOT latest-pointer consistency audit。
- `S104`: S103 后刷新 goal-completion audit。
- `S105`: S104 后刷新 remaining-blocker closure。
- `S106`: 刷新 deploy-preflight blocker current readback。
- `S107`: S106 后刷新 remaining-blocker closure。
- `S108`: S107 后刷新 goal-completion audit。
- `S109`: 用 Rust Club source evidence 加固 coordinate write blocker。
- `S110`: S109 后刷新 remaining-blocker closure。
- `S111`: 加固 relation identity blocker next-action tasks。
- `S112`: 用 S111 relation 和 S109 coordinate evidence 刷新 deploy preflight blocker。
- `S113`: S112 后刷新 remaining blocker closure。
- `S114`: 把历史用户命令总账对账到当前 S109/S111/S112/S113 blocker，标记 `15` 个 stale/missing-current finding。
- `S115`: 从 S86/S87/S89/S111 生成 relation identity write-gate starter packet，选出 `12` 个 high-risk + `12` 个 non-high starter rows，`27` 个任务，仍 blocked。

## Verification Status

Passed in current S114/S115 slice:

- `python -m pytest tools\stage7_rewrite\tests\test_audit_weekly_user_command_ledger_current_status.py -q`
- `npm run weekly:user-command-ledger:current-status`
- `python -m pytest tools\stage7_rewrite\tests\test_audit_weekly_user_command_ledger_current_status.py tools\stage7_rewrite\tests\test_audit_weekly_goal_completion.py tools\stage7_rewrite\tests\test_audit_weekly_ssot_pointer_consistency.py -q`
- `npm run weekly:goal-completion:audit ... --out-dir tools\stage7_rewrite\reports\weekly_goal_completion_audit_s114_20260601`
- `npm run weekly:ssot-pointer-consistency:audit -- --out-dir tools\stage7_rewrite\reports\weekly_ssot_pointer_consistency_audit_s114_20260601`
- `python -m pytest tools\stage7_rewrite\tests\test_build_atlas_relation_identity_write_gate_starter_packet.py -q`
- `npm run weekly:atlas-dj-identity:write-gate-starter`
- `npm run weekly:goal-completion:audit ... --out-dir tools\stage7_rewrite\reports\weekly_goal_completion_audit_s115_20260601`

Not run by design:

- OpenClaw / weekly automatic pipeline.
- Tencent/Amap/map provider/geocode calls.
- WeChat DevTools rendered automation.
- Deploy/upload/review.
- DB/graph/vector/public pointer writes.
- Coordinate writes.
- LLM/API calls, secret reads, service restarts.

## Current Blockers

1. Coordinate blocker:
   - `S109` still has safe-to-claim latest `false`.
   - Rust Club address captured: `大庆市龙凤区东风新村学伟大街 大庆市黎明湖酒吧一条街三号集装箱`.
   - No accepted provider coordinate is recorded.

2. Relation/identity blocker:
   - `S111` still has relation blockers `2045`.
   - Approved write-gate rows `0`.
   - Write-gate candidates `0`.
   - `S115` only creates a starter review queue; it does not authorize a DB write.

3. DevTools rendered blocker:
   - `S101/S100` still indicate dirty environment / protocol mismatch.
   - No rendered pass artifact exists.

4. Deploy/upload blocker:
   - `S112/S113` keep final preflight blocked because coordinate and relation gates are still red.

## Next Best Entry

Open first:

- `reports/WEEKLY_ATLAS_RELATION_IDENTITY_WRITE_GATE_STARTER_S115_20260601.md`
- `tools/stage7_rewrite/reports/atlas_relation_identity_write_gate_starter_s115_20260601/atlas_relation_identity_write_gate_starter_tasks.jsonl`

Why:

- This is the newest actionable blocker packet.
- It turns the broad `2045` relation/identity blocker into concrete starter review work.
- It keeps all production writes disabled while allowing real progress on DB1/DB2/DB3 identity unification.

Suggested next safe slice:

1. Build an `S116` report-only source-ref/disposition workbench for the 24 selected S115 starter rows.
2. For each row, require:
   - source_ref or original post evidence,
   - identity match notes,
   - field preservation notes,
   - explicit keep/split/merge/discard disposition,
   - proof that event/venue/collaborator/mixtape/social/bio/avatar fields will not be lost.
3. Do not write DB until validated rows produce positive approved write-gate candidates.

## Warnings / Pitfalls

- Do not treat `coverage_complete=true` as write authorization. S89 only proves every row is represented in review evidence.
- Do not treat same normalized name as same entity. S111 explicitly blocks this.
- Do not treat the Rust Club address as accepted coordinate evidence. S109 says captured address is not enough.
- Do not re-run OpenClaw or weekly automatic pipelines while S46 freeze is active.
- Do not use old S30/S33/S46 ledger claims as current status. S114 marks the historical ledger stale against S109/S111/S112/S113.
- Do not claim front-end rendered coverage from static tests alone.
- Do not “fix” by empty-field overwrites; S47/S48 exist because empty fields can destroy older valid data.

## OpenHuman Import Status

- imported: no
- source_id: none
- chunk_ids: none
- reason: OpenHuman MCP exposed help/read tools but no ingest/write tool in this session; direct Windows shell attempt `openhuman memory ingest ... -n atlas-huaidj -v` failed because `openhuman` is not on PATH. Markdown handoff is written as the canonical artifact.

## HTML Companion Artifact Status

- html_path: `docs/longrun/atlas-route-external-db-20260531/handoffs/HANDOFF_S1_S115_ATLAS_HUAIDJ_20260601.html`
- opened: no
- reason: HTML companion is generated for local review, but no browser open was needed for this handoff-only request.
