# DeepSeekTUI 下一步优化计划

目标：让 DeepSeekTUI 能直接接手 Atlas Core 三库合一后续优化，但所有输出都必须是候选/审阅/解释包，由 Codex 或人工审批后才进入写路径。

## P0：扩大 shadow diff 覆盖

优先级：最高
原因：当前 20 条 API path 已经 0 回归，但生产消费者比这 20 条更多。继续扩大 shadow matrix 比急着切生产更安全。

任务：

- 增加更多 DJ 名称样本：高频、低频、大小写混合、中文名、别名、符号名。
- 增加更多 venue/city/event/source evidence lookup 样本。
- 增加 organizer/label graph seed 样本，尤其 `dj_org_rollup` 相关路径。
- 增加随机抽样：从 `canonical_subject`、`dj_profile`、`performance_event`、`evidence_ref` 中取 bounded random sample。
- 输出每轮 diff report 和 markdown summary。

验收：

- regression finding 仍为 0，或每个 regression 有明确 `known_compat_gap`/`blocked_private_evidence` 解释。
- leak finding 为 0。
- source hashes unchanged 为 true。
- 不启动生产写入。

## P1：把旧兼容表纳入正式 compatibility contract

优先级：高
原因：这次最大坑不是 core schema，而是旧脚本依赖旧 read model 的字段、rank、source_count、org rollup。兼容表必须从临时救火变成正式 contract。

任务：

- 在 schema tests 里把以下表列为 expected compat contract：
  - `compat_canonical_subject`
  - `compat_dj_profile`
  - `compat_search_document`
  - `compat_dj_org_rollup`
  - `compat_graph_window_cache`
  - `compat_activity_event_detail`
  - `compat_activity_evidence_ref`
- 给 exporter 增加字段级 contract：旧字段名不删、不改类型。
- 增加 `dj_venue_rollup` exact-first 或 difference-budget 设计；当前覆盖不回退，但 count 大于旧库。
- 明确哪些 compat 字段来自旧 read model，哪些来自 core fact derivation。

验收：

- 老表旧字段完整。
- 旧脚本不理解的新字段保持可忽略。
- `Stage7AtlasSqliteStore` 无代码改动可打开候选 serving DB。

## P2：DB2/OpenClaw external-link staging 接入

优先级：高
原因：外链和 source-fetch 不能再直接拼 DB3 身份，否则会重复制造三库身份不一致。

任务：

- 把 `748` external link evidence 继续留在 `external_link_evidence`。
- 消费 DB2 external-link prewrite lane：
  - `522` report-only merge candidates
  - `452` unique prewrite candidates
  - 当前 quality-ready subset `64`
- 所有 S119/S120 `entity_search_id` 必须先通过 `entity_legacy_id` 映射。
- 每条 external link 只能进入以下状态之一：
  - `candidate`
  - `blocked`
  - `accepted_for_graph`
- 保持 raw URL redaction，不输出 raw URL。

验收：

- 无 DB2/DB3 写入。
- 无 raw URL 输出。
- 所有 rejected/blocked 有原因。
- 不直接 join DB3 `dj_profile.dj_id`。

## P3：DB3 identity resolution approval packet

优先级：高
原因：`348` same-normalized blocker 是生产 promotion 最大门槛之一。必须先做审批包，不能直接写。

任务：

- 从 `identity_resolution_case` 中优先处理 `38` source-backed candidates。
- 生成每个 case 的 packet：
  - canonical entity proposal
  - legacy IDs
  - evidence refs
  - conflict fields
  - accept/reject/defer/needs_more_evidence 条件
- `93` manual review 和 `217` external evidence required 保持 pending。
- 禁止空字段覆盖 richer relation/history/source fields。

验收：

- `approved_for_s232d4_count=0` 直到人工/控制器明确审批。
- `db_write_allowed_now_count=0`。
- 每个 packet 有 evidence path 和 stop condition。

## P4：read model performance and deterministic rebuild

优先级：中
原因：Atlas serving read model 已到 GB 级，任何 unindexed fallback 都会拖慢长跑。

任务：

- 给每个 `NOT EXISTS` fallback 前置 explain/index check。
- 增加 rebuild timing report。
- 对 `search_document_fts` 和 unicode61 companion 增加 query sample timing。
- 给 `graph_window_cache`、`dj_org_rollup`、`activity_evidence_ref` 增加 row count/readback hash。

验收：

- safe runner 每阶段耗时记录。
- 无卡死进程。
- 重建可重复，source hash unchanged。

## P5：promotion gate 预案

优先级：等 P0-P4 后
原因：生产切换不是技术上能跑就可以，需要 release gate 和用户批准。

必须全部满足：

- S121 升级版 join coverage 无 blocking finding。
- DB3 relation integrity blocker 归零，或全部有明确 defer/blocked 解释。
- `npm run weekly:deploy-upload:preflight` required failed 为 0。
- `Stage7AtlasSqliteStore` tests 通过。
- miniapp tests 通过。
- Atlas web smoke 通过。
- 用户明确批准 production pointer 切换。

禁止：

- DeepSeekTUI 自己决定 production promotion。
- 因为 shadow diff 0 regression 就覆盖生产 DB。
- 因为 38 source-backed candidates 看起来可靠就执行 S232D-4。

## 为什么按这个顺序

1. 先扩大 shadow diff，因为它最能保护旧消费者。
2. 再固化 compat contract，因为旧库字段兼容优先级高于 schema 美观。
3. 再接 external-link staging，因为外链身份映射必须从 core 统一。
4. 再处理 identity approval，因为这是生产切换前的最大风险。
5. 最后才考虑 promotion gate，因为生产切换需要多系统证据和用户批准。
