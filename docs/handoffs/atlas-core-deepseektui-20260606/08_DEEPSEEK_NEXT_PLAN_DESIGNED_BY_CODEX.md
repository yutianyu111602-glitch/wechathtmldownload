# DeepSeekTUI 下一轮计划：Codex 设计版

生成时间：2026-06-06
设计来源：`superpowers:brainstorming` + `superpowers:writing-plans`
状态：可交给 DeepSeekTUI 执行候选分析；不授权生产写入

## 结论

DeepSeekTUI 下一轮先做 `P0 shadow matrix expansion`，再做 `P1 legacy compatibility contract`，然后只对 `38` source-backed identity cases 设计 approval packet 草稿。不要直接进入 DB3 S232D-4，不要动生产 DB。

## 为什么这样排

当前最重要的事实是：Atlas Core 候选已经 20-path API shadow diff 零回归，但旧消费者面更大。先扩大 shadow coverage，可以用最低风险发现旧脚本/旧 API 的真实依赖。身份合并虽然重要，但如果 read model 兼容还没完全固定，先合并身份会放大后续回滚成本。

## 给 DeepSeek 的执行顺序

1. 读 `START_HERE_FOR_DEEPSEEK_TUI.md`，确认安全边界。
2. 读 `01_ACCEPTANCE_REPORT.md`，确认最终候选和验收状态。
3. 读 `docs/superpowers/specs/2026-06-06-atlas-core-deepseektui-next-optimization-design.md`。
4. 读 `docs/superpowers/plans/2026-06-06-atlas-core-deepseektui-next-optimization.md`。
5. 只执行 plan 的 Task 1-3，输出候选 packet 到 `/home/pc/deepseek-dream/outbox/`。
6. 等 Codex review 后，再继续 Task 4-7。

## 第一批只跑 Tasks 1-3

第一批范围：

- Task 1：current authority packet
- Task 2：shadow matrix expansion candidate
- Task 3：legacy compatibility contract candidate

第一批禁止：

- 不跑 expanded shadow diff。
- 不处理全部 38 identity cases。
- 不写 DB。
- 不改仓库文件。

## DeepSeek 必须产出的文件

```text
/home/pc/deepseek-dream/outbox/YYYYMMDD_HHMMSS_atlas_core_current_authority_candidate.md
/home/pc/deepseek-dream/outbox/YYYYMMDD_HHMMSS_atlas_core_current_authority_candidate.jsonl
/home/pc/deepseek-dream/outbox/YYYYMMDD_HHMMSS_atlas_core_shadow_matrix_expansion_candidate.md
/home/pc/deepseek-dream/outbox/YYYYMMDD_HHMMSS_atlas_core_shadow_matrix_expansion_candidate.jsonl
/home/pc/deepseek-dream/outbox/YYYYMMDD_HHMMSS_atlas_core_compat_contract_candidate.md
/home/pc/deepseek-dream/outbox/YYYYMMDD_HHMMSS_atlas_core_compat_contract_candidate.jsonl
```

每条 JSONL 必须包含：

```json
{"codex_verification_needed": true, "evidence_paths": ["..."]}
```

## 后续批次

Codex review 第一批后，DeepSeek 才能继续：

- Task 4：38 source-backed identity approval packet draft
- Task 5：external-link staging candidate
- Task 6：performance/rebuild risk candidate
- Task 7：next safe batch recommendation

## 权威文件

- Design spec：`docs/superpowers/specs/2026-06-06-atlas-core-deepseektui-next-optimization-design.md`
- Execution plan：`docs/superpowers/plans/2026-06-06-atlas-core-deepseektui-next-optimization.md`
- WSL2 handoff main：`/home/pc/deepseektui-handoffs/atlas-core-20260606`
- Repo handoff：`docs/handoffs/atlas-core-deepseektui-20260606`

## 停止条件

DeepSeek 遇到以下任一情况必须停止并报告：

- final candidate 目录不存在。
- safe execution decision 不是 `atlas_core_safe_execution_passed`。
- source hashes changed。
- 任何报告显示 production/source DB write 已执行。
- 需要读取 secret/cookie/.env/profile。
- 需要写 DB、部署、上传、提审、发布。
- 依赖缺失导致命令不能只读执行。

## 给 DeepSeek 的一句话

先证明你读懂了当前 authority 和旧消费者兼容面，再建议扩大 shadow；不要碰生产，不要越过 DB3 identity gate。
